import argparse
import copy
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from subprocess import Popen, PIPE, run

# Ensure that Python can find .py files in utils/py/ regardless of where the script
# is run from by adding the path holding the code (<lib_path>) to sys.path
# __file__ 					= <lib_path>/transcriber/py/diplomat.py
# os.path.dirname(__file__) = <lib_path>/transcriber/py/
# '../../' 					= up two levels, i.e., <lib_path>
lib_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../utils'))
if lib_path not in sys.path:
	sys.path.insert(0, lib_path)

from py.constants import *
from py.utils import (get_tuning, add_unique_id, remove_namespace_from_tag, handle_namespaces, 
					  parse_tree, get_main_MEI_elements, collect_xml_ids, unwrap_markup_elements,
					  print_all_elements, pretty_print, get_isodate)

SHIFT_INTERVALS = {D: -5, E: -3, F: -2, F6Eb: -2, G: 0, G6F: 0, A: 2, A6G: 2}
SMUFL_LUTE_DURS = {'f': 'fermataAbove',
				   1: 'luteDurationDoubleWhole',
				   2: 'luteDurationWhole',
				   4: 'luteDurationHalf', 
				   8: 'luteDurationQuarter',
				   16: 'luteDuration8th',
				   32: 'luteDuration16th',
				   '.': 'augmentationDot'
				  }
JAVA_PATH = 'tools.music.PitchKeyTools' # <package>.<package>.<file>
JAVA_PATH_CONV = 'tbp.editor.Editor' # <package>.<package>.<file>
VERBOSE = False
URI_MEI = None
URI_XML = None
XML_ID_KEY = None
ORIG_XML_IDS = None
XML_IDS = None 
TUNING = None
KEY = None 
TYPE = None 


# Helper functions -->
def call_java(cmd: list, use_Popen: bool=False): # -> dict:
	"""
	NB For debugging: set, where this function is called, use_Popen=True.
    - output is what the stdout (System.out.println()) printouts from Java return;
      it is passed to json.loads() and must be formatted as json
    - errors is what the stderr (System.err.println()) debugging printouts from
      Java return; it is printed when use_Popen=True and doesn't have to be formatted
	"""

	# Replace empty strings
	for i in range(len(cmd)):
		if cmd[i] == '':
			cmd[i] = '__EMPTY__'

	# For debugging
	if use_Popen:
		process = Popen(cmd, stdout=PIPE, stderr=PIPE, shell=False)
		output, errors = process.communicate()
		outp = output.decode('utf-8') # str
		errors = errors.decode('utf-8') # str
		print("errors: " + errors)
		print("output: " + outp)
	# For normal use
	else:
		process = run(cmd, capture_output=True, shell=False)
		outp = process.stdout.decode('utf-8') # str
#		outp = process.stdout # bytes
#		print(outp)

	return json.loads(outp)


def make_element(name: str, parent: ET.Element=None, atts: list=[]): # -> ET.Element:
	"""
	Convenience method for creating an ET.Element or ET.SubElement object with a one-liner. 
	Useful because, in the conventional way, any attributes that contain a dot in their 
	name must be set separately with set():

	e = ET.Element(name, att_1='<val_1>', att_2='<val_2>', ..., att_n='<val_n>')
	e.set('<att_with_dot>', '<val>')

	or 

	se = ET.SubElement(parent, name, att_1='<val_1>', att_2='<val_2>', ..., att_n='<val_n>')
	se.set('<att_with_dot>', '<val>')
	"""
	o = ET.Element(name) if parent == None else ET.SubElement(parent, name)
	for a in atts:
		o.set(a[0], a[1])

	return o


# Main functions -->
def handle_encodingDesc(encodingDesc: ET.Element, ns: dict, args: argparse.Namespace): # -> None:
	"""
	Basic structure of <encodingDesc>:

	<encodingDesc>
	  <appInfo>
	    <application>
	      <name/>
	      <p/>
	      <p/>
	    </application>  
	  </appInfo>
	  ...
	</encodingDesc>
	"""

	# Handle appInfo
	appInfo = encodingDesc.find('.//mei:appInfo', ns)
	# Make new <application>
	application = make_element(f'{URI_MEI}application', 
						 	   atts=[(XML_ID_KEY, add_unique_id('a', XML_IDS)[-1]),
							   		 ('isodate', get_isodate()), 
							   		 ('version', args.version)]
							  )
	ET.SubElement(application, f'{URI_MEI}name', 
				  **{f'{XML_ID_KEY}': add_unique_id('n', XML_IDS)[-1]}
				 ).text = 'abtab -- transcriber'
	ET.SubElement(application, f'{URI_MEI}p', 
				  **{f'{XML_ID_KEY}': add_unique_id('p', XML_IDS)[-1]}
				 ).text = f'Input file: {args.file}'
	ET.SubElement(application, f'{URI_MEI}p', 
				  **{f'{XML_ID_KEY}': add_unique_id('p', XML_IDS)[-1]}
				 ).text = f'Output file: {os.path.splitext(args.file)[0]}-dipl{MEI}'
	# If there is no <appInfo>: create one
	if appInfo is None:
		appInfo = ET.SubElement(encodingDesc, f'{URI_MEI}appInfo',
								**{f'{XML_ID_KEY}': add_unique_id('ai', XML_IDS)[-1]}
				 			   )
	# Else: remove any existing abtab <application>s
	else:
		for a in appInfo.findall('.//mei:application', ns):
			name = a.find('.//mei:name', ns)
			if name is not None and name.text and name.text.startswith('abtab'):
				appInfo.remove(a)
	# Add <application> 			
	appInfo.append(application)


def handle_scoreDef(scoreDef: ET.Element, ns: dict, args: argparse.Namespace): # -> None:
	"""
	Basic structure of <scoreDef>:

	<scoreDef>
	  <staffGrp>
	    <staffGrp>
	      <staffDef/>
	     (<staffDef/>)
	    </staffGrp>  
	    <staffDef/>
	  </staffGrp>
	</scoreDef>

	The nested inner <staffGrp> is for the notehead notation and contains one <staffDef> in case 
	of a single staff, otherwise two; the lower <staffDef> is for the tablature. 
	"""

	staffGrp = scoreDef.find('mei:staffGrp', ns)

	# 1. Tablature <staffDef>: adapt or remove  
	tab_staffDef = staffGrp.find('mei:staffDef', ns)
	tab_meterSig = tab_staffDef.find('mei:meterSig', ns)
	tab_mensur = tab_staffDef.find('mei:mensur', ns)
	tab_tuning = tab_staffDef.find('mei:tuning', ns)
	tab_not_type = tab_staffDef.get('notationtype')
	is_first_scoreDef = tab_tuning != None

	# Set global vars corresponding to args that can have INPUT as value
	global TUNING # dlaute customisation: args.tuning == A
	if args.tuning == INPUT:
		# If tab_tuning == None, no tuning is provided in the input file
		TUNING = get_tuning(tab_tuning, ns) if tab_tuning != None else G
	else:
		TUNING = args.tuning

	global TYPE # dlaute customisation: args.type not used because args.tablature == n
	if args.type == INPUT:
		# If tab_not_type == None, no type is provided in the input file 
		TYPE = tab_not_type if tab_not_type != None else NOTATIONTYPES[FLT]
	else:
		TYPE = NOTATIONTYPES[args.type]

	global KEY # dlaute customisation: args.key == 0
	if args.key == INPUT:
		KEY = str(call_java(['java', '-cp', args.classpath, JAVA_PATH, args.dev, 'key', TUNING, args.file]))
	else:
		KEY = args.key

	# Adapt
	if args.tablature == YES:
		n = tab_staffDef.get('n')
		lines = tab_staffDef.get('lines')

		# Reset <staffDef> attributes
		tab_staffDef.set('n', str(int(n) + (1 if args.score == SINGLE else 2)))
		if TYPE != NOTATIONTYPES[GLT]:
			tab_staffDef.set('lines', '5' if lines == '5' and TYPE == NOTATIONTYPES[FLT] else '6')
			tab_staffDef.set('notationtype', TYPE)
		# Reset <tuning>
		# <tuning> is only used in first staffDef, not in those for any subsequent <section>s 
		if is_first_scoreDef:
			tab_tuning.clear()
			tab_tuning.set(XML_ID_KEY, add_unique_id('t', XML_IDS)[-1])
			for i, (pitch, octv) in enumerate(TUNINGS[TUNING]):
				course = ET.SubElement(tab_tuning, f'{URI_MEI}course',
								   	   **{f'{XML_ID_KEY}': add_unique_id('c', XML_IDS)[-1]},
								   	   n=str(i + 1),
								       pname=pitch[0],
								       oct=str(octv),
								       accid='' if len(pitch) == 1 else ('f' if pitch[1] == 'b' else 's')
								      )
	# Remove
	else:
		staffGrp.remove(tab_staffDef)

	# 2. Notehead <staffGrp>: create and set as first element in <staffGrp>
	nh_staffGrp = ET.Element(f'{URI_MEI}staffGrp', 
							 **{f'{XML_ID_KEY}': add_unique_id('sg', XML_IDS)[-1]})
	if args.score == DOUBLE:
		nh_staffGrp.set('symbol', 'bracket')
		nh_staffGrp.set('bar.thru', 'true')
	staffGrp.insert(0, nh_staffGrp)
	# Add <staffDef>(s)
	for i in [1] if args.score == SINGLE else [1, 2]:
		nh_staffDef = ET.SubElement(nh_staffGrp, f'{URI_MEI}staffDef',
									**{f'{XML_ID_KEY}': add_unique_id('sd', XML_IDS)[-1]},
									n=str(i),
									lines='5'
								   )
		if i == 1:
			nh_staffDef.set('dir.dist', '4')
		# Add <clef>
		# <clef> is only used in first staffDef, not in those for any subsequent <section>s
		if is_first_scoreDef:
			if args.score == SINGLE:
				clef = make_element(f'{URI_MEI}clef', 
									parent=nh_staffDef, 
									atts=[(XML_ID_KEY, add_unique_id('c', XML_IDS)[-1]),
									      ('shape', 'G'), 
										  ('line', '2'),
										  ('dis', '8'), 
										  ('dis.place', 'below')]
								  	)
			else:
				clef = ET.SubElement(nh_staffDef, f'{URI_MEI}clef', 
									 **{f'{XML_ID_KEY}': add_unique_id('c', XML_IDS)[-1]},
									 shape='G' if i==1 else 'F',
									 line='2' if i==1 else '4'
									)
		# Add <keySig>
		# <keySig> is only used in first staffDef, not in those for any subsequent <section>s
		# NB Theoretically, the <section> could be in a different key -- but currently a single key 
		#    is assumed for the whole piece
		if is_first_scoreDef:
			keySig = ET.SubElement(nh_staffDef, f'{URI_MEI}keySig',
								   **{f'{XML_ID_KEY}': add_unique_id('ks', XML_IDS)[-1]},
								   sig=_get_MEI_keysig(KEY),
								   mode='minor' if args.mode == MINOR else 'major'
								  )
		# Add <meterSig> or <mensur>
		if tab_meterSig is not None:
			nh_meterSig = copy.deepcopy(tab_meterSig)
			nh_meterSig.set(XML_ID_KEY, add_unique_id('ms', XML_IDS)[-1])
			nh_staffDef.append(nh_meterSig)
		elif tab_mensur is not None:
			nh_mensur = copy.deepcopy(tab_mensur)
			nh_mensur.set(XML_ID_KEY, add_unique_id('m', XML_IDS)[-1])
			nh_staffDef.append(nh_mensur)


def _get_MEI_keysig(key: str): # -> str:
#	if key == INPUT:
#		return str(0)
#	else:
#	return key + 's' if int(key) > 0 else str(abs(int(key))) + 'f'
	if int(key) == 0:
		return key
	else:
		return key + 's' if int(key) > 0 else str(abs(int(key))) + 'f'


# NEW!
def clean_measure_number(mnum: str): # -> str:
	match = re.match(r'^(\d+)', mnum)
	return match.group(1) if match else None


# NEW!
def copy_and_transform_staff(elem: ET.Element, parent_map: dict): # -> ET.Element:
	elems_to_replace = [f'{URI_MEI}tabGrp', f'{URI_MEI}note', f'{URI_MEI}rest']
	notes = {} # (key = xml:id of <note> (tab) : value = <note> (CMN))
	chords = {} # (key = xml:id of <tabGrp> : value = <chord> or <rest> (!))

	new_elem = make_new_element(elem, parent_map) if elem.tag in elems_to_replace else ET.Element(elem.tag)
	# If elem is a <tabGrp>
	if elem.tag == f'{URI_MEI}tabGrp':
		chords[elem.get(XML_ID_KEY)] = new_elem
	# If elem is a <note>
	if elem.tag == f'{URI_MEI}note':
		notes[elem.get(XML_ID_KEY)] = new_elem

	# Copy all attributes of non-altered elements; reset <xml:id>
	if elem.tag not in elems_to_replace:
		elem_name = get_element_name(elem)
		for attr, val in elem.attrib.items():
			new_elem.set(attr, val if attr != f'{URI_XML}id' else add_unique_id(elem_name[0], XML_IDS)[-1])

	# Recursively transform children
	for child in elem:
#		# Do not copy tabDurSym onto new_elem
#		if child.tag == f'{URI_MEI}tabDurSym': # and elem.tag == f'{URI_MEI}tabGrp':
#			# If parent is not <tabGrp>: <tabDurSym> is wrapped
#			# - wrap the corresponding dir the same way
#			# - remove the wrapper here
#			continue
		# Do not copy <beam> onto new_elem, only its contents
		if child.tag == f'{URI_MEI}beam':
			for grandchild in child:
				new_grandchild, chords_grandchild, notes_grandchild = copy_and_transform_staff(grandchild, parent_map)
				if new_grandchild is not None:
					new_elem.append(new_grandchild)
				chords.update(chords_grandchild)
				notes.update(notes_grandchild)
			continue
		
		new_child, chords_child, notes_child = copy_and_transform_staff(child, parent_map)
		if new_child is not None:
			new_elem.append(new_child)
		chords.update(chords_child)
		notes.update(notes_child)

	return (new_elem, chords, notes)


# NEW!
def make_new_element(elem: ET.Element, parent_map: dict): # -> ET.Element:
	if elem.tag == f'{URI_MEI}tabGrp':
		# If elem contains notes: new_elem is a <chord>
		if any(child.tag == f'{URI_MEI}note' for child in elem.iter()):
			new_elem = make_element(f'{URI_MEI}chord', 
									atts=[(XML_ID_KEY, add_unique_id('c', XML_IDS)[-1]),
										  ('dur', elem.get('dur')),
										  ('stem.visible', 'false')]
								   )
		# If elem contains no notes: new_elem is a <rest>
		else:
			new_elem = make_element(f'{URI_MEI}rest', 
									atts=[(XML_ID_KEY, add_unique_id('r', XML_IDS)[-1]),
										  ('dur', elem.get('dur'))]
								   )
	elif elem.tag == f'{URI_MEI}note':
		try:
			midi_pitch = _get_midi_pitch(int(elem.get('tab.course')), 
									     int(elem.get('tab.fret')), 
										 TUNING)
		except TypeError:
			raise Exception(f'Element {elem.tag} with attributes\
							{elem.attrib} is missing tab.course or tab.fret')
		new_elem = make_element(f'{URI_MEI}note',  
								atts=[(XML_ID_KEY, add_unique_id('n', XML_IDS)[-1]),
									  ('pname', f'{midi_pitch}'), # dummy value that is overwritten
									  ('oct', str(_get_octave(midi_pitch))),
									  ('head.fill', 'solid')]
							   )
	elif elem.tag == f'{URI_MEI}rest':
		tabGrp = find_ancestor_with_tag(elem, parent_map, f'{URI_MEI}tabGrp')
		new_elem = make_element(f'{URI_MEI}rest',  
								atts=[(XML_ID_KEY, add_unique_id('r', XML_IDS)[-1]),
									  ('dur', tabGrp.get('dur'))]
							   )

	return new_elem


# NEW!
def find_ancestor_with_tag(elem: ET.Element, parent_map: dict, tag: str): # -> ET.Element | None:
	"""
	Walks up the tree from `elem` using `parent_map` and returns the first ancestor
	with the given `tag`. Returns None if no such ancestor is found.

	Arguments:
	- elem: The starting element
	- parent_map: A dictionary mapping each element to its parent
	- tag: The fully qualified tag to search for (e.g., f'{URI_MEI}<tag>')

	Returns:
	- The first ancestor element with the given tag, or None.
	"""
	parent = parent_map.get(elem)
	while parent is not None:
		if parent.tag == tag:
			return parent
		parent = parent_map.get(parent)
	return None


# NEW!
def get_element_name(elem: ET.Element): # -> str:
	"""
	Strips leading URL from tag.
	"""
	return elem.tag.split('}', 1)[1]


# NEW!
def handle_section_NEW(section: ET.Element, ns: dict, args: argparse.Namespace): # -> tuple:
	tab_staff_n = '2' if args.score == SINGLE else '3'
	measure = clean_measure_number(section.find('.//mei:measure', ns).get('n'))

	notes_unspelled_by_ID = []
	staffs_and_dirs = [] # contains, per measure: old staff, new staff, combined dirs (flag dirs + other)
	parent_map = {c: p for p in section.iter() for c in p} # this is a *reverse* (child -> parent) lookup dict!
	tab_to_CMN_note_ids = {}

	# Iterate recursively over <section> and copy/transform content of all <measure>s, i.e., 
	# (1) all staffs (NB: a staff is not necessarily a direct child of <measure>)
	# (2) all direct children of <measure> that are not <staff>, e.g., <dir>, <add>, <supplied>, ...
	it = section.iter()
	for elem in it:
		if elem.tag == f'{URI_MEI}measure':
			if clean_measure_number(elem.get('n')) != measure:
				measure = clean_measure_number(elem.get('n'))

			curr_staffs_and_dirs = ()
			other = []
			for melem in [child for child in elem]:
				# 1. Copy/transform <staff>
				if melem.tag == f'{URI_MEI}staff':
					melem.set('n', tab_staff_n)
					new_staff, chords, notes = copy_and_transform_staff(melem, parent_map)
					new_staff.set('n', '1')
#					print(pretty_print(elem))
					print('measure', measure)
					print(pretty_print(new_staff))

					flag_dirs = []
					# Make rhythm flag <dir>s for rests
					for r in new_staff.findall('.//mei:rest', ns):
						flag_dir = _make_rhythm_symbol_dir(r.get(XML_ID_KEY), r.get('dur'), r.get('dots'), ns)
						flag_dirs.append(flag_dir)
						for child in list(r):
							if child.tag == f'{URI_MEI}tabDurSym':
								r.remove(child)

					# Make rhythm flag <dir>s for chords
					to_remove = []
					for c in new_staff.findall('.//mei:chord', ns):
						flag_dir = _make_rhythm_symbol_dir(c.get(XML_ID_KEY), c.get('dur'), c.get('dots'), ns)
						# tabDurSyms can be direct children of chord or placed inside wrapper elements
						for el in list(c):
							# tabDurSym is a direct child
							if el.tag == f'{URI_MEI}tabDurSym':
								flag_dirs.append(flag_dir)
								# Remove el from c
								to_remove.append(el)
							# tabDurSym is placed inside wrapper
							elif el.find('.//mei:tabDurSym', ns) is not None:
								tds = el.find('.//mei:tabDurSym', ns)
								# el may contain multiple elements, e.g.
								# <supplied ...>
								#     <tabDurSym .../>
								#	  <note .../>
								# </supplied>
								# Make copy with only the tabDurSym (to be added to flag_dirs) 
								el_for_flag_dirs = copy.deepcopy(el)
								el_for_flag_dirs.set(XML_ID_KEY, add_unique_id(get_element_name(el)[0], XML_IDS)[-1])
								for child in list(el_for_flag_dirs):
									el_for_flag_dirs.remove(child)
								el_for_flag_dirs.append(flag_dir)
								flag_dirs.append(el_for_flag_dirs)
								# Adapt original to keep any other elements (to remain in c if not empty)
								for child in list(el):
									if child is tds:
										el.remove(child)
								if not list(el):
									to_remove.append(el)

#								# In el, replace tabDurSym with flag dir; add complete el
#								found = False
#								for parent in el.iter():
#									for i, child in enumerate(list(parent)):
#										if child is tds:
#											parent.remove(tds)
#											parent.insert(i, flag_dir)
#											found = True
#											break
#									if found: 
#										break
#								flag_dirs.appen(el)
#								to_remove.append(el)
						for el in to_remove:
							c.remove(el)
						to_remove.clear()

					# Add tab staff, CMN staff, and flag dirs to list
					curr_staffs_and_dirs = (melem, new_staff, flag_dirs)

					# Add to notes_unspelled_by_ID
					for n in list(notes.values()):
						notes_unspelled_by_ID.append([n.get(XML_ID_KEY), measure, n.get('pname')])

#					# For efficiency: skip all descendants of staff
#					for descendant in elem.iter():
#						next(it, None)

				# 2. Copy/transform any other element that is a direct child of <measure>
				else:
					melem.set('label', 'tab')
					melem_CMN = copy.deepcopy(melem)
					melem_CMN.set('label', 'CMN')
					# NB: if elem is a wrapper elem (<add>, <del>, ...), there may be multiples or combinations
					# of <dir>, <fing>, or <fermata> inside it; therefore, the for-loop is needed
					if any(e.tag == f'{URI_MEI}dir' for e in melem.iter()):	
						# <dir> has @staff to determine its position: adapt in elem and elem_CMN
						dirs = [melem] if melem.tag == f'{URI_MEI}dir' else melem.findall('.//mei:dir', ns) 
						for d in dirs:
							d.set('staff', tab_staff_n)
						dirs_CMN = [melem_CMN] if melem_CMN.tag == f'{URI_MEI}dir' else melem_CMN.findall('.//mei:dir', ns)
						for d in dirs_CMN:
							d.set('staff', '1')
							# Move hold (tenute) symbol above the staff
							if d.get('type') == 'hold':
								d.set('place', 'above')
					if any(e.tag == f'{URI_MEI}fing' for e in melem.iter()):
						# TODO: replace with a flag <dir> when RS with fingering 'hook' is in SMuFL  
						# <fing> has @startid to determine its position: adapt only in elem_CMN 
						fings_CMN = [melem_CMN] if melem_CMN.tag == f'{URI_MEI}fing' else melem_CMN.findall('.//mei:fing', ns)
						for f in fings_CMN:
							id_note_tab = f.get('startid').lstrip('#')
							id_note_CMN = notes[id_note_tab].get(XML_ID_KEY)
							f.set('startid', f'#{id_note_CMN}')
					if any(e.tag == f'{URI_MEI}fermata' for e in melem.iter()):
						# <fermata> has @startid to determine its position: adapt only in elem_CMN
						fermatas_CMN = [melem_CMN] if melem_CMN.tag == f'{URI_MEI}fermata' else melem_CMN.findall('.//mei:fermata', ns)
						for f in fermatas_CMN:
							id_tabGrp = f.get('startid').lstrip('#')
							id_chord = chords[id_tabGrp].get(XML_ID_KEY)
							f.set('startid', f'#{id_chord}')
					# Adapt <xml:id>s
					for e in melem_CMN.iter():
						e.set(XML_ID_KEY, add_unique_id(get_element_name(e)[0], XML_IDS)[-1])
					# Add to other
					other.append(melem_CMN)

			# Add other dirs to flag dirs
			curr_staffs_and_dirs[-1].extend(other)
			staffs_and_dirs.append(curr_staffs_and_dirs)

	# Insert CMN staffs before tab staffs; insert combined dirs after CMN staffs 
	for tab_staff, CMN_staff, comb_dirs in staffs_and_dirs:
		parent = parent_map[tab_staff]
		index = list(parent).index(tab_staff)
		# Insert CMN staff
		parent.insert(index, CMN_staff)

		# Insert flag dirs after CMN staff
		for i, comb_dir in enumerate(comb_dirs):
			parent.insert(index + 1 + i, comb_dir) 

#	print(pretty_print(section))
	return (section, notes_unspelled_by_ID)


def handle_section(section: ET.Element, ns: dict, args: argparse.Namespace): # -> tuple:
	"""
	Basic structure of <section>:

	<section>
	  <measure>
	    <staff>
	      <layer>
	        <chord/>, <rest/>, <space/>
	        ...
	      </layer>   
	    </staff>
	   (<staff/>)
	    <staff>
	      <layer>
	        <tabGrp/>
	        ...
	      </layer>
	    </staff>
	    <dir/>
	    ...
	    <other/>
	  </measure>
	  ...
	</section>

	The upper <staff> is for the notehead notation; the lower for the tablature. 
	The <dir>s contain the flags for the notehead notation, and can be followed 
	by other elements such as <fermata> or <fing>. In case of a double staff for 
	the notehead notation, there is also a middle staff. 
	"""

	tab_notes_by_ID = {}
	tabGrps_by_ID = {}
	notes_unspelled_by_ID = []
	regular_elements = [f'{URI_MEI}{e}' for e in ['measure', 'staff', 'layer', 'beam', 'tabGrp', 'tabDurSym', 'note', 'rest']]
	# Markup elements used only in diplomatic transcriptions of E-LAUTE project:
	markup_elements = [f'{URI_MEI}{e}' for e in (MARKUP_ELEMENTS + ['sic'])]
	tab_elements = [f'{URI_MEI}{e}' for e in ['tabGrp', 'tabDurSym', 'note', 'rest']]

	# Unwrap all markup elements
	unwrap_markup_elements(section, markup_elements)

	for measure in section.iter(f'{URI_MEI}measure'):
		# 1. Collect any non-regular elements in <measure> and remove them from it
		non_regular_elements = [elem for elem in measure.iter() if elem.tag not in regular_elements]
		# Collect
		elems_removed_from_measure = []
		for elem in non_regular_elements:
			# Get all elements with the same tag as elem
			matching_elements = measure.findall(f'.//{elem.tag}', ns)
			if matching_elements:
				elems_removed_from_measure.extend(matching_elements)
		# Remove
		for elem in elems_removed_from_measure:
			for parent in measure.iter():
				if elem in parent:
					parent.remove(elem)
					break

		# 2. Handle regular <staff> elements
		# a. Tablature <staff>
		# Adapt
		tab_staff = measure.find('mei:staff', ns)
		tab_staff.set('n', str(int(tab_staff.attrib['n']) + (1 if args.score == SINGLE else 2)))
		tab_layer = tab_staff.find('mei:layer', ns)
		# Remove
		if args.tablature == NO:
			measure.remove(tab_staff)

		# b. Notehead <staff>s 
		# Add <staff>s to <measure>
		nh_staff_1 = ET.Element(f'{URI_MEI}staff', 
								**{f'{XML_ID_KEY}': add_unique_id('s', XML_IDS)[-1]},
								n='1')
		nh_staff_2 = ET.Element(f'{URI_MEI}staff', 
								**{f'{XML_ID_KEY}': add_unique_id('s', XML_IDS)[-1]},
								n='2')
		measure.insert(0, nh_staff_1)
		if args.score == DOUBLE:
			measure.insert(1, nh_staff_2)

		# Add <layer>s to <staff>s
		nh_layer_1 = ET.SubElement(nh_staff_1, f'{URI_MEI}layer', 
								   **{f'{XML_ID_KEY}': add_unique_id('l', XML_IDS)[-1]},
								   n='1')
		nh_layer_2 = ET.SubElement(nh_staff_2, f'{URI_MEI}layer', 
								   **{f'{XML_ID_KEY}': add_unique_id('l', XML_IDS)[-1]},
								   n='1')

		# Add <rest>s and <chord>s and/or<space>s to <layer>s; collect <dir>s
		rhythm_symbol_dirs = []
		for tabGrp in tab_layer.iter(f'{URI_MEI}tabGrp'):
			dur = tabGrp.get('dur')
			dots = tabGrp.get('dots')
			flag = tabGrp.find('mei:tabDurSym', ns)
			rest = tabGrp.find('mei:rest', ns)
			space = tabGrp.find('mei:space', ns)
			xml_id_tabGrp = tabGrp.get(XML_ID_KEY)

			# Add <rests> (i.e., add <space>s). Possibilities
			# 1. <tabGrp> containing <tabDurSym/> + <rest> (rhythm-flag looking or rest-looking): explicit
			#    --> <space> with <dir>
			# 2. a. <tabGrp> containing <rest> (rhythm-flag looking) (~= 3.): implicit
			#    --> <space> with <dir>
			#    b. <tabGrp> containing <rest> (rest-looking): explicit
			#    --> <space>  
			# 3. <tabGrp> containing <tabDurSym/> (above or inside the system): implicit
			#    --> <space> with <dir>
			# NB Old approach: create xml_id_rest_1 (_2), rest_1 (_2), and rests instead of 
			#    xml_id_space_1 (_2), space_1 (_2), and spaces
			rest_case_1 = flag != None and rest != None
			rest_case_2a = flag == None and rest != None and rest.get('glyph.name') in SMUFL_LUTE_DURS.values()
			rest_case_2b = flag == None and rest != None and rest.get('glyph.name') not in SMUFL_LUTE_DURS.values()
			rest_case_3 = flag != None and rest == None and len(tabGrp) == 1
			if rest_case_1 or rest_case_2a or rest_case_2b or rest_case_3:
				xml_id_space_1 = add_unique_id('s', XML_IDS)[-1]
				xml_id_space_2 = add_unique_id('s', XML_IDS)[-1]

				# 1. Add <space>s to <layer>s
				space_1 = make_element(f'{URI_MEI}space', 
									  parent=nh_layer_1, 
									  atts=[(XML_ID_KEY, xml_id_space_1),
										 	('dur', dur)]
									 )
				space_2 = make_element(f'{URI_MEI}space', 
									  parent=nh_layer_2, 
									  atts=[(XML_ID_KEY, xml_id_space_2),
										 	('dur', dur)]
									 )

				# 2. Add <dir>
				if not rest_case_2b:
					rhythm_symbol_dirs.append(_make_rhythm_symbol_dir(xml_id_space_1, dur, dots, ns))

				# 3. Map tabGrp
				spaces = (space_1, None) if args.score == SINGLE else (space_1, space_2)
				tabGrps_by_ID[xml_id_tabGrp] = (tabGrp, spaces)
				# Map tab <rest>
				if rest != None:
					tab_notes_by_ID[rest.get(XML_ID_KEY)] = (rest, spaces)

			# Add <chord>s and/or <space>s	
			else:
				# 0. Create <chord>s and add <note>s to them
				# NB A <chord> cannot be added directly to the parent <layer> upon creation 
				#    because it may remain empty, and in that case must be replaced by a <space>
				xml_id_chord_1 = add_unique_id('c', XML_IDS)[-1]
				xml_id_chord_2 = add_unique_id('c', XML_IDS)[-1]
				chord_1 = make_element(f'{URI_MEI}chord', 
									   atts=[(XML_ID_KEY, xml_id_chord_1),
										     ('dur', dur), 
										   	 ('stem.visible', 'false')]
									  )
				chord_2 = make_element(f'{URI_MEI}chord', 
									   atts=[(XML_ID_KEY, xml_id_chord_2),
										   	 ('dur', dur), 
										   	 ('stem.visible', 'false')]
									  )
				for element in tabGrp:
					if element != flag and element != rest and element != space:
						try:
							midi_pitch = _get_midi_pitch(int(element.get('tab.course')), 
													 	 int(element.get('tab.fret')), 
													 	 TUNING)
						except TypeError:
							midi_pitch = -1
#							raise Exception(f"Element {element.tag} with attributes\
#											{element.attrib} is either missing tab.course or tab.fret")

						xml_id_note = add_unique_id('n', XML_IDS)[-1]
						nh_note = make_element(f'{URI_MEI}note', 
											   parent=chord_1 if args.score == SINGLE else\
												      (chord_1 if midi_pitch >= 60 else chord_2), 
											   atts=[(XML_ID_KEY, xml_id_note),
												  	 ('pname', None),
												     ('oct', str(_get_octave(midi_pitch))),
												     ('head.fill', 'solid')] if midi_pitch != -1 
												     else [(XML_ID_KEY, xml_id_note), 
														   ('visible', 'false')]
											  )
						# Map tab <note>
						tab_notes_by_ID[element.get(XML_ID_KEY)] = (element, nh_note)
						notes_unspelled_by_ID.append([xml_id_note, measure.get('n'), midi_pitch])

				# 1. Add <chord>s and/or <space>s to <layer>s
				xml_id_space = add_unique_id('s', XML_IDS)[-1]
				nh_space = make_element(f'{URI_MEI}space', 
										atts=[(XML_ID_KEY, xml_id_space),
											  ('dur', dur)]
									   )
				nh_layer_1.append(chord_1 if len(chord_1) > 0 else nh_space)
				if args.score == DOUBLE:
					nh_layer_2.append(chord_2 if len(chord_2) > 0 else nh_space)
				xml_id_reference = xml_id_chord_1 if len(chord_1) > 0 else xml_id_space

				# 2. Add <dir>
				if flag != None:
					rhythm_symbol_dirs.append(_make_rhythm_symbol_dir(xml_id_reference, dur, dots, ns))

				# 3. Map tabGrp
				chords = (chord_1, None) if args.score == SINGLE\
										 else (chord_1 if len(chord_1) > 0 else nh_space,\
										 	   chord_2 if len(chord_2) > 0 else nh_space)
				tabGrps_by_ID[xml_id_tabGrp] = (tabGrp, chords)

		# 3. Handle non-regular <measure> elements. These are elements that require <chord>, 
		#    <rest>, or <space> reference xml:ids, and must therefore be handled after all 
		#    regular <staff> elements are handled, and those reference IDs all exist
		curr_non_regular_elements = []
		for c in elems_removed_from_measure:
			# Fermata: needs <dir> (CMN) and <fermata> (= c; tab)
			if c.tag == f'{URI_MEI}fermata':
				# Add CMN <dir> (to rhythm_symbol_dirs)
				xml_id_tabGrp = c.get('startid').lstrip('#') # start after '#'
				xml_id_upper_chord = tabGrps_by_ID[xml_id_tabGrp][1][0].get(XML_ID_KEY)
				rhythm_symbol_dirs.append(_make_rhythm_symbol_dir(xml_id_upper_chord, 'f', None, ns))

				# Add c to list	
				if args.tablature == YES:
					curr_non_regular_elements.append(c)
			# Annotation: needs <annot> (CMN) and <annot> (= c; tab) 
			elif c.tag == f'{URI_MEI}annot':
				xml_id_referred = c.get('plist').lstrip('#') # start after '#'
				elem_referred = ORIG_XML_IDS.get(xml_id_referred)

				# If <annot> refers to a tab element
				# - add CMN <annot> to list
				# - if tablature is included, also add original <annot> (c) to list
				if elem_referred.tag in tab_elements:
					if elem_referred.tag == f'{URI_MEI}note' or elem_referred.tag == f'{URI_MEI}rest':
						xml_id_tab_elem = tab_notes_by_ID[xml_id_referred][1].get(XML_ID_KEY)
					elif elem_referred.tag == f'{URI_MEI}tabGrp':
						xml_id_tab_elem = tabGrps_by_ID[xml_id_tabGrp][1][0].get(XML_ID_KEY)
					elif elem_referred.tag == f'{URI_MEI}tabDurSym':
						pass # TODO refer to <dir> that represents <tabDurSym>
					annot = copy.deepcopy(c)
					annot.set('plist', '#' + xml_id_tab_elem)
					annot.set(XML_ID_KEY, add_unique_id('a', XML_IDS)[-1])
					curr_non_regular_elements.append(annot)
					if args.tablature == YES:
						curr_non_regular_elements.append(c)
				# If <annot> refers to a non-tab element
				# - add original <annot> (c) to list
				else:
					curr_non_regular_elements.append(c)
			# Fingering: needs <fing> (= c; tab)
			elif c.tag == f'{URI_MEI}fing':
				# Add c to list
				if args.tablature == YES:
					curr_non_regular_elements.append(c)
			# (Text) directive: needs <dir> (CMN) and <dir> (= c; tab)
			elif c.tag == f'{URI_MEI}dir':
				# Add CMN <dir> to list
				direc = copy.deepcopy(c)
				for e in direc.iter():
					e.set(XML_ID_KEY, add_unique_id(remove_namespace_from_tag(e.tag)[0], XML_IDS)[-1])
					if 'staff' in e.attrib:
						e.set('staff', '1') # probably not needed but doesn't hurt
					if 'startid' in e.attrib:
						xml_id_tabGrp = e.get('startid').lstrip('#') # start after '#'
						xml_id_upper_chord = tabGrps_by_ID[xml_id_tabGrp][1][0].get(XML_ID_KEY)
						e.set('startid', '#' + xml_id_upper_chord)
					if 'fontsize' in e.attrib:
						e.set('fontsize', 'small')
				curr_non_regular_elements.append(direc)

				# Add c to list	
				if args.tablature == YES:
					c.set('staff', '3' if args.score == DOUBLE else '2')
					curr_non_regular_elements.append(c)
			# Other
			else:
				# Add c to list
				curr_non_regular_elements.append(c)

		# 4. Add non-regular <measure> elements to completed <measure> in fixed sequence
		fermatas = [e for e in curr_non_regular_elements if e.tag == f'{URI_MEI}fermata']
		annots = [e for e in curr_non_regular_elements if e.tag == f'{URI_MEI}annot']
		fings = [e for e in curr_non_regular_elements if e.tag == f'{URI_MEI}fing']
		direcs = [e for e in curr_non_regular_elements if e.tag == f'{URI_MEI}dir']
		for e in rhythm_symbol_dirs + fermatas + annots + fings + direcs:
			measure.append(e)

		if VERBOSE:
			for elem in measure:
				print(elem.tag, elem.attrib)
				for e in elem:
					print(e.tag, e.attrib)
					for ee in e:
						print(ee.tag, ee.attrib)
						for eee in ee:
							print(eee.tag, eee.attrib)

	return (section, notes_unspelled_by_ID)


def _make_rhythm_symbol_dir(xml_id: str, dur: int, dots: int, ns: dict): # -> ET.Element:
	d = ET.Element(f'{URI_MEI}dir', 
				   **{f'{XML_ID_KEY}': add_unique_id('d', XML_IDS)[-1]},
				   place='above', 
				   startid='#' + xml_id
				  )
	
	# Non-fermata case
	if dur != 'f':
		make_element(f'{URI_MEI}symbol', 
					 parent=d, 
					 atts=[(XML_ID_KEY, add_unique_id('s', XML_IDS)[-1]),
						   ('glyph.auth', 'smufl'), 
						   ('glyph.name', SMUFL_LUTE_DURS[int(dur)])]
				   	)
		if dots != None:
			make_element(f'{URI_MEI}symbol', 
					     parent=d, 
						 atts=[(XML_ID_KEY, add_unique_id('s', XML_IDS)[-1]),
							   ('glyph.auth', 'smufl'), 
							   ('glyph.name', SMUFL_LUTE_DURS['.'])]
						)
	# Fermata case 
	else:
		make_element(f'{URI_MEI}symbol', 
					 parent=d, 
					 atts=[(XML_ID_KEY, add_unique_id('s', XML_IDS)[-1]),
						   ('glyph.auth', 'smufl'), 
						   ('glyph.name', SMUFL_LUTE_DURS['f'])]
				   	)

	return d


def _get_midi_pitch(course: int, fret: int, arg_tuning: str): # -> int:
	# Determine the MIDI pitches for the open courses
	abzug = 0 if not '-' in arg_tuning else 2
	open_courses = [67, 62, 57, 53, 48, (43 - abzug)]
	if arg_tuning[0] != G:
		shift_interv = SHIFT_INTERVALS[arg_tuning[0]]
		open_courses = list(map(lambda x: x + shift_interv, open_courses))
	return open_courses[course - 1] + fret


def _get_octave(midi_pitch: int): # -> int:
	c = midi_pitch - (midi_pitch % 12)
	return int((c / 12) - 1)


def spell_pitch(section: ET.Element, notes_unspelled_by_ID: list, args: argparse.Namespace): # -> None:
	# Dictionary for fast lookup of xml:ids
	xml_id_map = {e.get(XML_ID_KEY): e for e in section.iter() if XML_ID_KEY in e.attrib}

	grids_dict = call_java(['java', '-cp', args.classpath, JAVA_PATH, args.dev, 'grids', KEY, args.mode])
	mpcGrid = grids_dict['mpcGrid'] # list
	altGrid = grids_dict['altGrid'] # list
	pcGrid = grids_dict['pcGrid'] # list

	key_sig_accid_type = 'f' if int(KEY) <= 0 else 's'
	# Key sig accidentals as MIDI pitch classes (e.g. 10, 3)
	key_sig_accid_mpc = [mpcGrid[i] for i in range(len(altGrid)) if altGrid[i] == key_sig_accid_type]

	cmd = ['java', '-cp', args.classpath, JAVA_PATH, args.dev, 'pitch', json.dumps(notes_unspelled_by_ID), 
		   KEY, json.dumps(mpcGrid), json.dumps(altGrid), json.dumps(pcGrid), args.score]
	spell_dict = call_java(cmd)
#	accidsInEffect = [[[]], [[]], [[]], [[]], [[]]] # double flats, flats, naturals, sharps, double sharps
	for key, val in spell_dict.items():
		midi_pitch = int(val['pitch'])
		midi_pitch_class = midi_pitch % 12
		accidsInEffect = val['accidsInEffect'] # double flats, flats, naturals, sharps, double sharps

		# a. The note is in key	and there are no accidentals in effect
		no_aie = not any(p for s1 in accidsInEffect for s2 in s1 for p in s2) # True if accidsInEffect is completely empty
		if midi_pitch_class in mpcGrid and no_aie:
			pname = pcGrid[mpcGrid.index(midi_pitch_class)]
			accid = ''
			accid_ges = ''
			# In case of key sig accidental 
			if midi_pitch_class in key_sig_accid_mpc:
				if args.accidentals == YES:
					accid = key_sig_accid_type
				else:	
					accid_ges = key_sig_accid_type
		# b. The note is in key	and there are accidentals in effect / the note is not in key
		else:
			pname = val['pname'] # str
			accid = val['accid'] # str
			accid_ges = val['accid.ges'] # str
			if args.accidentals == YES and accid_ges != '':
				accid = accid_ges
				accid_ges = ''
			accidsInEffect = val['accidsInEffect'] # list
		
		# Adapt <note>
		note = xml_id_map.get(key)
		if midi_pitch != -1:
			note.set('pname', pname)
		if accid != '':
			note.set('accid', accid)
		elif accid_ges != '':
			note.set('accid.ges', accid_ges)


# Principal code -->
def transcribe(in_path: str, out_path: str, args: argparse.Namespace): # -> None:
	# 0. File processing
	in_file = args.file
	filename, ext = os.path.splitext(in_file) # in_file is already basename (see method call in transcriber.py)
	out_file = filename + '-dipl' + MEI
	# Get file contents as MEI string
	if ext != MEI:
		# As in abtab converter: provide three opts, always with their default vals, and no user opts
		opts_java = '-u -t -y -h'
		default_vals_java = 'i y i n/a' 
		user_opts_vals_java = ''
		cmd = ['java', '-cp', args.classpath, JAVA_PATH_CONV, args.dev, opts_java, default_vals_java,\
			   user_opts_vals_java, 'false', in_file, filename + MEI]
		res = call_java(cmd)
		mei_str = res['content']
	else:
		with open(os.path.join(in_path, in_file), 'r', encoding='utf-8') as file:
			mei_str = file.read()
	# Get version
	with open(os.path.join(args.libpath, 'VERSION'), 'r', encoding='utf-8') as file:
		version = file.read()
	args.version = version

	print(args.file)
	dgdfg

	# 0. Preliminaries 
	# a. Handle namespaces
	ns = handle_namespaces(mei_str)
	global URI_MEI
	URI_MEI = f'{{{ns['mei']}}}'
	global URI_XML
	URI_XML = f'{{{ns['xml']}}}'
	global XML_ID_KEY
	XML_ID_KEY = f'{URI_XML}id'
	# b. Get the tree, root (<mei>), main MEI elements (<meiHead>, <music>), and <score>
	tree, root = parse_tree(mei_str)
	meiHead, music = get_main_MEI_elements(root, ns)
	score = music.find('.//mei:score', ns)
	# c. Collect all xml:ids; map the original xml:ids
	global XML_IDS
	XML_IDS = collect_xml_ids(root, XML_ID_KEY)
	global ORIG_XML_IDS
	ORIG_XML_IDS = { # TODO keep?
		elem.attrib[XML_ID_KEY]: elem for elem in root.iter() if XML_ID_KEY in elem.attrib
	}

	# 1. Handle <encodingDesc>
	encodingDesc = meiHead.find('.//mei:encodingDesc', ns)
	handle_encodingDesc(encodingDesc, ns, args)

	# 2. Handle <scoreDef>s
	scoreDefs = score.findall('.//mei:scoreDef', ns)
	for scoreDef in scoreDefs:
		handle_scoreDef(scoreDef, ns, args)

	# 3. Handle <section>s
	sections = score.findall('mei:section', ns)
	for section in sections:
		section, notes_unspelled_by_ID = handle_section(section, ns, args)
		spell_pitch(section, notes_unspelled_by_ID, args)

	# 4. Fix indentation
	ET.indent(tree, space='\t', level=0)

	# 5. Add processing instructions (<?xml> declaration and <?xml-model>  
	# processing instructions), which are not included in root 
	lines = mei_str.split('\n')
	declaration = lines[0] + '\n'
	model_pi = ''
	for line in lines:
		if line[1:].startswith('?xml-model'):
			model_pi += line + '\n'
	xml_str = ET.tostring(root, encoding='unicode')
	xml_str = f'{declaration}{model_pi}{xml_str}'
	
	# 6. Write to file
	with open(os.path.join(out_path, out_file), 'w', encoding='utf-8') as file:
		file.write(xml_str)
