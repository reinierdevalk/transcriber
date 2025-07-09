"""
Relevant Python documentation
- https://docs.python.org/3/library/subprocess.html
- https://docs.python.org/3/library/xml.etree.elementtree.html

Useful links
- running Java code from CLI
  - https://stackoverflow.com/questions/16137713/how-do-i-run-a-java-program-from-the-command-line-on-windows
- using subprocess
  - https://www.datacamp.com/tutorial/python-subprocess
  - https://stackoverflow.com/questions/59214417/winerror-2-file-not-found-with-subprocess-run
  - https://stackoverflow.com/questions/21406887/subprocess-changing-directory
  - https://stackoverflow.com/questions/77239936/how-to-call-subprocess-efficiently-and-avoid-calling-it-in-a-loop
  - https://stackoverflow.com/questions/9322796/keep-a-subprocess-alive-and-keep-giving-it-commands-python
- calling Java from Python
  - https://www.askpython.com/python/examples/call-java-using-python
  - https://www.tutorialspoint.com/how-can-we-read-from-standard-input-in-java
- other
  - https://stackoverflow.com/questions/1953761/accessing-xmlns-attribute-with-python-elementree
  - https://stackoverflow.com/questions/28813876/how-do-i-get-pythons-elementtree-to-pretty-print-to-an-xml-file
  - https://www.geeksforgeeks.org/xml-parsing-python/
  - https://w3c.github.io/smufl/latest/tables/renaissance-lute-tablature.html

ElementTree tips
- getting elements and attributes
  - get('<att>') gets an element's attribute
  - find() and findall()
    - NB URI_MEI must look like
      URI_MEI = '{http://www.music-encoding.org/ns/mei}'
      NB ns must look like
      ns = {'mei': 'http://www.music-encoding.org/ns/mei', 'xml': 'http://www.w3.org/XML/1998/namespace'}
    - find() finds the first matching direct child (depth = 1)
      - find('mei:scoreDef', ns)
      - find({f'{URI_MEI}scoreDef')
    - find('.//...') finds the first matching element at any depth (recursive search)  
      - find('.//mei:scoreDef', ns)
      - find(f'.//{URI_MEI}scoreDef')
    - findall() finds all matching direct children (depth = 1)
      - findall('mei:scoreDef', ns)
      - findall({f'{URI_MEI}scoreDef')
    - findall('.//...') finds all matching elements at any depth (recursive search)
      - findall('.//mei:scoreDef', ns)
      - findall(f'.//{URI_MEI}scoreDef')
  - use findall() with XPath: see https://docs.python.org/3/library/xml.etree.elementtree.html#elementtree-xpath
- namespaces
  - element namespaces: the namespace dict is mostly useful for element searches (find(), findall())
  - attribute namespaces: need to be provided explicitly in the get(), or constructed from the namespace dict

"""

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
from py.utils import get_tuning, add_unique_id, handle_namespaces, parse_tree, get_main_MEI_elements, collect_xml_ids, print_all_elements, pretty_print

SHIFT_INTERVALS = {F: -2, F6Eb: -2, G: 0, G6F: 0, A: 2, A6G: 2}
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
ADD_ACCID_GES = True
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
def handle_scoreDef(scoreDef: ET.Element, ns: dict, args: argparse.Namespace): # -> None
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
	return key + 's' if int(key) > 0 else str(abs(int(key))) + 'f'


def make_new_element(elem: ET.Element): # -> ET.Element
	if elem.tag == f'{URI_MEI}tabGrp':
		contains_notes = any(child.tag == f'{URI_MEI}note' for child in elem.iter())
		# If elem contains notes: new_elem is a chord
		if contains_notes:
			new_elem = make_element(f'{URI_MEI}chord', 
									atts=[(XML_ID_KEY, add_unique_id('c', XML_IDS)[-1]),
										  ('dur', elem.get('dur')),
										  ('stem.visible', 'false')]
								   )
		# If elem contains no notes: new_elem is a rest
		else:
			new_elem = make_element(f'{URI_MEI}rest', 
									atts=[(XML_ID_KEY, add_unique_id('c', XML_IDS)[-1]),
										  ('dur', elem.get('dur'))]
								   )
#	elif elem.tag == f'{URI_MEI}tabDurSym':
#		# Walk up the tree to find <tabGrp> parent
#		parent_elem = elem
#		while parent_elem is not None:
#			if parent_elem.tag == f'{URI_MEI}tabGrp':
#				tabGrp = parent_elem
#				dur = tabGrp.get('dur')
#				dots = tabGrp.get('dots')
#				xml_id = tabGrp.get(XML_ID_KEY)
#				break
#			parent_elem = parent_map.get(parent_elem)
#		new_elem = _make_dir(xml_id, dur, dots, ns) # xml_id (=startid) must be replaced with the xml_id of the corresponding chord
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
#									  ('pname', 'None'),
									  ('oct', str(_get_octave(midi_pitch))),
									  ('head.fill', 'solid')]
							   )
	elif elem.tag == f'{URI_MEI}rest':
		new_elem = make_element(f'{URI_MEI}rest',  
								atts=[(XML_ID_KEY, add_unique_id('r', XML_IDS)[-1]),
									  'dur', elem.get('dur')]
							   )

	return new_elem


def copy_and_transform_staff(elem: ET.Element): # -> ET.Element
	elems_to_replace = [f'{URI_MEI}tabGrp', f'{URI_MEI}note', f'{URI_MEI}rest']
	notes = {} # (key = xml:id of note (tab) : value = note (CMN))
	chords = {} # (key = xml:id of tabGrp : value = chord)

	new_elem = make_new_element(elem) if elem.tag in elems_to_replace else ET.Element(elem.tag)
	# If elem is a tabGrp
	if elem.tag == f'{URI_MEI}tabGrp':
		chords[elem.get(XML_ID_KEY)] = new_elem #(new_elem, any(child.tag == f'{URI_MEI}tabDurSym' for child in elem.iter()))
	# If elem is a note
	if elem.tag == f'{URI_MEI}note':
		notes[elem.get(XML_ID_KEY)] = new_elem

	# Copy all attributes of non-altered elements; reset xml:id
	if elem.tag not in elems_to_replace:
		elem_name = elem.tag.split('}', 1)[1] # strip URL bit from tag
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
		# Do not copy beam onto new_elem, only its contents
		if child.tag == f'{URI_MEI}beam':
			for grandchild in child:
				new_grandchild, chords_grandchild, notes_grandchild = copy_and_transform_staff(grandchild)
				if new_grandchild is not None:
					new_elem.append(new_grandchild)
				chords.update(chords_grandchild)
				notes.update(notes_grandchild)
			continue
		
		new_child, chords_child, notes_child = copy_and_transform_staff(child)
		if new_child is not None:
			new_elem.append(new_child)
		chords.update(chords_child)
		notes.update(notes_child)

	return (new_elem, chords, notes)


def clean_measure_number(mnum: str): # -> str
	match = re.match(r'^(\d+)', mnum)
	return match.group(1) if match else None


def handle_section(section: ET.Element, ns: dict, args: argparse.Namespace): # -> tuple
	tab_staff_n = '2' if args.score == SINGLE else '3'
	measure = clean_measure_number(section.find('.//mei:measure', ns).get('n'))

	notes_unspelled_by_ID = []
	staffs_and_dirs = [] # contains, per measure, old staff, new staff, flag dirs (list), other (list)
	parent_map = {c: p for p in section.iter() for c in p} # this is a *reverse* (child -> parent) lookup dict!
	tab_to_CMN_note_ids = {}

	# Iterate recursively over <section> and copy/transform content of all <measure>s, i.e., 
	# (1) all staffs (NB: a staff is not necessarily a diret child of <measure>)
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
#					print(pretty_print(elem))
					new_staff, chords, notes = copy_and_transform_staff(melem)
					new_staff.set('n', '1')
					print(pretty_print(new_staff))
					
			
#					print(list(chords.keys()))
#					print('-------')
#					for item in list(chords.values()): 
#						print(item[0].get(XML_ID_KEY), item[1])

#					# Now that chords exists: set correct reference xml:id for <dir>s
#					dirs = new_staff.findall('.//mei:dir', ns)
#					print('HIERRRR')
#					for z in dirs:
#						print(pretty_print(z))
#					print(list(chords.keys()))
					
#					for d in dirs:
#						xml_id_tabGrp = d.get('startid').lstrip('#')
#						xml_id_chord = chords[xml_id_tabGrp].get(XML_ID_KEY)
#						d.set('startid', f'#{xml_id_chord}')

					# Make <dir>s for rhythm flags
#					chords_in_staff = new_staff.findall('.//mei:chord', ns)
					flag_dirs = []
					to_remove = []
					for c in new_staff.findall('.//mei:chord', ns):
						flag_dir = _make_dir(c.get(XML_ID_KEY), c.get('dur'), c.get('dots'), ns)
						# tabDurSyms can be direct children of chord or placed inside wrapper elements
						for el in list(c):
							# tabDurSym is a direct child: add flag_dir directly
							if el.tag == f'{URI_MEI}tabDurSym':
#								flag_dir = _make_dir(c.get(XML_ID_KEY), c.get('dur'), c.get('dots'), ns)
								flag_dirs.append(flag_dir)
								# Remove el from c
								to_remove.append(el)
							# tabDurSym is placed inside wrapper: replace tabDurSym with flag_dir in el; add el
							elif el.find('.//mei:tabDurSym', ns) is not None:
								tds = el.find('.//mei:tabDurSym', ns)
#								flag_dir = _make_dir(c.get(XML_ID_KEY), c.get('dur'), c.get('dots'), ns)
								# In el, replace tabDurSym with flag dir; add complete el
								found = False
								for parent in el.iter():
									for i, child in enumerate(list(parent)):
										if child is tds:
											parent.remove(tds)
											parent.insert(i, flag_dir)
											found = True
											break
									if found: 
										break
								flag_dirs.append(el)
								to_remove.append(el)

								# measure 2: wrapper (el) contains more than only a tabDurSym (also note)
								# make deep copy of wrapper and change xml:ids 
								# --> in deep copy, replace tabDurSym with flag dir; remove remainder (note) from wrapper; add to flag_dirs
								# --> in original, remove tabDurSym 

						for el in to_remove:
							c.remove(el)
						to_remove.clear()

#					for t in tabDurSyms:
#						# Walk up the tree to find <tabGrp> parent
#						parent_elem = elem
#						while parent_elem is not None:
#							if parent_elem.tag == f'{URI_MEI}tabGrp':
#								tabGrp = parent_elem
#								dur = tabGrp.get('dur')
#								dots = tabGrp.get('dots')
#								xml_id = tabGrp.get(XML_ID_KEY)
#								break
#						parent_elem = parent_map.get(parent_elem)


					# Collect <dir>s for rhythm flags
#					flag_dirs = []
#					for c in list(chords.values()):
#						if c[1] == True:
#							flag_dirs.append(_make_dir(c[0].get(XML_ID_KEY), c[0].get('dur'), c[0].get('dots'), ns))
##						print(pretty_print(_make_dir(c.get(XML_ID_KEY), c.get('dur'), c.get('dots'), ns)))

					# Add tab staff, CMN staff, and flag dirs to list
					curr_staffs_and_dirs = (melem, new_staff, flag_dirs)
#					staffs_and_dirs.append((elem, new_staff, flag_dirs))

					# Add to notes_unspelled_by_ID
					for n in list(notes.values()):
						notes_unspelled_by_ID.append([n.get(XML_ID_KEY), measure, n.get('pname')])

#					# For efficiency: skip all descendants of staff
#					for descendant in elem.iter():
#						next(it, None)

		# Get other direct children of <measure>
#		other = [child if child.tag != f'{URI_MEI}staff' for child in ]

				# 2. Copy/transform any other element that is a direct child of <measure>
				else:
#				for other_elem in other:
#				if elem.tag != f'{URI_MEI}section':
#					if parent_map[elem].tag == f'{URI_MEI}measure':
					melem.set('label', 'tab')
					melem_CMN = copy.deepcopy(melem)
					melem_CMN.set('label', 'CMN')
					print('TAG', melem.tag)
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
					if any(e.tag == f'{URI_MEI}fing' for e in melem.iter()):
						# TODO: replace with a flag <dir> when RS with fingering 'hook' are in SMuFL  
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
#							id_chord = chords[id_tabGrp][0].get(XML_ID_KEY)
							f.set('startid', f'#{id_chord}')
					# Adapt <xml:id>s
					for e in melem_CMN.iter():
						elem_name = e.tag.split('}', 1)[1] # strip URL bit from tag
						e.set(XML_ID_KEY, add_unique_id(elem_name[0], XML_IDS)[-1])
					# Add to other
					other.append(melem_CMN)

			# Add other dirs to flag dirs
			curr_staffs_and_dirs[-1].extend(other)
#			curr_staffs_and_dirs = curr_staffs_and_dirs + (other,)
#			print(len(curr_staffs_and_dirs[-1]))
			print('HIER')
			for i, item in enumerate(curr_staffs_and_dirs):
				if i == 0 or i == 1:
					print(item.tag)
				else:
					for meti in item:
						print('*********')
						print(pretty_print(meti))

			staffs_and_dirs.append(curr_staffs_and_dirs)


						# dir: always copy, change staff= and place= (for type="hold", to above)  

						# If elem has somewhere something with a reference to a note that is
						# - not fing: copy/transform it, remove original if tab == NO
						#   - tenuto sign
						# - fing: don't copy/transform, remove original if tab == NO 
						# If not: always just leave it in, change staff 
						# - fol. 3r
						#         

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


def handle_section_OLD(section: ET.Element, ns: dict, args: argparse.Namespace): # -> tuple
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
	tab_elements = [f'{URI_MEI}{e}' for e in ['tabGrp', 'tabDurSym', 'note', 'rest']]

	for measure in section.iter(f'{URI_MEI}measure'):
		# 0. Collect any non-regular elements in <measure> and remove them from it
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

		# 1. Handle regular <staff> elements
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

		# Add <rest>s, and <chord>s and/or<space>s to <layer>s; collect <dir>s
		dirs = []
		for tabGrp in tab_layer.iter(f'{URI_MEI}tabGrp'):
			dur = tabGrp.get('dur')
			dots = tabGrp.get('dots')
			flag = tabGrp.find('mei:tabDurSym', ns)
			rest = tabGrp.find('mei:rest', ns)
			space = tabGrp.find('mei:space', ns)
			xml_id_tabGrp = tabGrp.get(XML_ID_KEY)

			# Add <rest>s. Rests can be implicit (a <tabGrp> w/ only a <tabDurSym>) or
			# explicit (a <tabGrp> w/ a <rest> (and possibly a <tabDurSym>)). Both are
			# transcribed as a <rest> in the CMN
			if (flag != None and (len(tabGrp) == 1) or rest != None): # or space != None):
				xml_id_rest_1 = add_unique_id('r', XML_IDS)[-1]
				xml_id_rest_2 = add_unique_id('r', XML_IDS)[-1]

				# 1. Add <rest>s to <layer>s
				rest_1 = make_element(f'{URI_MEI}rest', 
									  parent=nh_layer_1, 
									  atts=[(XML_ID_KEY, xml_id_rest_1),
										 	('dur', dur)]
									 )
				rest_2 = make_element(f'{URI_MEI}rest', 
									  parent=nh_layer_2, 
									  atts=[(XML_ID_KEY, xml_id_rest_2),
										 	('dur', dur)]
									 )

				# 2. Add <dir>
				dirs.append(_make_dir(xml_id_rest_1, dur, dots, ns))

				# 3. Map tabGrp
				rests = (rest_1, None) if args.score == SINGLE else (rest_1, rest_2)
				tabGrps_by_ID[xml_id_tabGrp] = (tabGrp, rests)
				# Map tab <rest>
				if rest != None:
					tab_notes_by_ID[rest.get(XML_ID_KEY)] = (rest, rests) 

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
							raise Exception(f"Element {element.tag} with attributes\
											{element.attrib} is either missing tab.course or tab.fret")

						xml_id_note = add_unique_id('n', XML_IDS)[-1]
						nh_note = make_element(f'{URI_MEI}note', 
											   parent=chord_1 if args.score == SINGLE else\
												      (chord_1 if midi_pitch >= 60 else chord_2), 
											   atts=[(XML_ID_KEY, xml_id_note),
												  	 ('pname', None),
												     ('oct', str(_get_octave(midi_pitch))),
												     ('head.fill', 'solid')]
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
					dirs.append(_make_dir(xml_id_reference, dur, dots, ns))

				# 3. Map tabGrp
				chords = (chord_1, None) if args.score == SINGLE\
										 else (chord_1 if len(chord_1) > 0 else nh_space,\
										 	   chord_2 if len(chord_2) > 0 else nh_space)
				tabGrps_by_ID[xml_id_tabGrp] = (tabGrp, chords)

		# 2. Handle non-regular <measure> elements. These are elements that require <chord>, 
		#    <rest>, or <space> reference xml:ids, and must therefore be handled after all 
		#    regular <staff> elements are handled, and those reference IDs all exist
		curr_non_regular_elements = []
		for c in elems_removed_from_measure:
			# Fermata: needs <dir> (CMN) and <fermata> (= c; tab)
			if c.tag == f'{URI_MEI}fermata':
				# Make <dir> for CMN and add 
				xml_id_tabGrp = c.get('startid').lstrip('#') # start after '#'
				xml_id_upper_chord = tabGrps_by_ID[xml_id_tabGrp][1][0].get(XML_ID_KEY)
				dirs.append(_make_dir(xml_id_upper_chord, 'f', None, ns))

				# Add to list	
				if args.tablature == YES:
					curr_non_regular_elements.append(c)
			# Annotation: needs <annot> (CMN) and <annot> (= c; tab) 
			elif c.tag == f'{URI_MEI}annot':
				xml_id_referred = c.get('plist').lstrip('#') # start after '#'
				elem_referred = ORIG_XML_IDS.get(xml_id_referred)				

				# If <annot> refers to a tab element
				# - always add CMN <annot> (annot) to list
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
				# - always add <annot> (c) to list
				else:
					curr_non_regular_elements.append(c)

##				# Make <annot> for CMN				
#				xml_id_note = tab_notes_by_ID[xml_id_referred][1].get(XML_ID_KEY)
#				annot = copy.deepcopy(c)
#				annot.set('plist', '#' + xml_id_note)
#				annot.set(XML_ID_KEY, add_unique_id('a', XML_IDS)[-1])
#
#				# Add to list
#				curr_non_regular_elements.append(annot)
#				if args.tablature == YES:
#					curr_non_regular_elements.append(c)
			# Fingering: needs <fing> (= c; tab)
			elif c.tag == f'{URI_MEI}fing':
				# Add to list
				if args.tablature == YES:
					curr_non_regular_elements.append(c)
			# Other
			else:
				# Add to list
				curr_non_regular_elements.append(c)

		# 3. Add non-regular <measure> elements to completed <measure> in fixed sequence
		fermatas = [e for e in curr_non_regular_elements if e.tag == f'{URI_MEI}fermata']
		annots = [e for e in curr_non_regular_elements if e.tag == f'{URI_MEI}annot']
		fings = [e for e in curr_non_regular_elements if e.tag == f'{URI_MEI}fing']
		for e in dirs + fermatas + annots + fings:
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


def _make_dir(xml_id: str, dur: int, dots: int, ns: dict): # -> 'ET.Element'
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


def _get_midi_pitch(course: int, fret: int, arg_tuning: str): # -> int
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


def spell_pitch(section: ET.Element, notes_unspelled_by_ID: list, args: argparse.Namespace): # -> None
	# Dictionary for fast lookup of xml:ids
	xml_id_map = {e.get(XML_ID_KEY): e for e in section.iter() if XML_ID_KEY in e.attrib}

	grids_dict = call_java(['java', '-cp', args.classpath, JAVA_PATH, args.dev, 'grids', KEY, args.mode])
	mpcGrid = grids_dict['mpcGrid'] # list
	altGrid = grids_dict['altGrid'] # list
	pcGrid = grids_dict['pcGrid'] # list

	if ADD_ACCID_GES:
		key_sig_accid_type = 'f' if int(KEY) <= 0 else 's'
		# Key sig accidentals as MIDI pitch classes (e.g. 10, 3)
		key_sig_accid_mpc = [mpcGrid[i] for i in range(len(altGrid)) if altGrid[i] == key_sig_accid_type]

	cmd = ['java', '-cp', args.classpath, JAVA_PATH, args.dev, 'pitch', json.dumps(notes_unspelled_by_ID), 
		   KEY, json.dumps(mpcGrid), json.dumps(altGrid), json.dumps(pcGrid)]
	spell_dict = call_java(cmd)
	accidsInEffect = [[], [], [], [], []] # double flats, flats, naturals, sharps, double sharps
	for key, val in spell_dict.items():
		midi_pitch = int(val['pitch'])
		midi_pitch_class = midi_pitch % 12

		# a. The note is in key	and there are no accidentals in effect
		if midi_pitch_class in mpcGrid and not any(accidsInEffect):
			pname = pcGrid[mpcGrid.index(midi_pitch_class)]
			accid = ''									
			if ADD_ACCID_GES:
				accid_ges = key_sig_accid_type if midi_pitch_class in key_sig_accid_mpc else ''
		# b. The note is in key	and there are accidentals in effect / the note is not in key
		else:
			pname = val['pname'] # str
			accid = val['accid'] # str
			if ADD_ACCID_GES:
				accid_ges = val['accid.ges'] # str
			accidsInEffect = val['accidsInEffect'] # list
		
		# Adapt <note>
		note = xml_id_map.get(key)
		note.set('pname', pname)
		if ADD_ACCID_GES:
			# accid.ges overrules accid
			if accid_ges != '':
				if args.accidentals == YES:
					note.set('accid', accid_ges)
				else:
					note.set('accid.ges', accid_ges)
			else: 
				if accid != '':
					note.set('accid', accid)
		else:
			if accid != '':
				note.set('accid', accid)


# Principal code -->
def transcribe(in_file: str, in_path: str, out_path: str, args: argparse.Namespace): # -> None
	# 0. File processing
	filename, ext = os.path.splitext(os.path.basename(in_file))
	out_file = filename + '-dipl' + MEI
	args.file = in_file # NB already the case when using -f
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

	# 1. Preliminaries 
	# a. Handle namespaces
	ns = handle_namespaces(mei_str)
	global URI_MEI
	URI_MEI = f'{{{ns['mei']}}}'
	global URI_XML
	URI_XML = f'{{{ns['xml']}}}'
	global XML_ID_KEY
	XML_ID_KEY = f'{URI_XML}id'
	# b. Get the tree, root (<mei>), and main MEI elements (<meiHead>, <score>)
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

	# 2. Handle <scoreDef>s
	scoreDefs = score.findall('.//mei:scoreDef', ns)
	for scoreDef in scoreDefs:
		handle_scoreDef(scoreDef, ns, args)

	# 3. Handle <section>s
	sections = score.findall('mei:section', ns)
	for section in sections:
		section, notes_unspelled_by_ID = handle_section(section, ns, args)
#		section, notes_unspelled_by_ID = handle_section_OLD(section, ns, args)
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
