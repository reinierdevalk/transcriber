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
from py.utils import get_tuning, add_unique_id, handle_namespaces, parse_tree, get_main_MEI_elements, collect_xml_ids

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
# TODO these always all caps?
java_path = 'tools.music.PitchKeyTools' # <package>.<package>.<file>
java_path_conv = 'tbp.editor.Editor' # <package>.<package>.<file>
verbose = False
add_accid_ges = True
URI_MEI = None
URI_XML = None
XML_ID_KEY = None
xml_ids = None
tuning = None


def _call_java(cmd: list, use_Popen: bool=False): # -> dict:
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


def _create_element(name: str, parent: ET.Element=None, atts: list=[]): # -> ET.Element:
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

	global tuning
	if args.tuning == INPUT:
		# Tuning provided in input file: set to provided tuning
		if tab_tuning != None:
			tuning = get_tuning(tab_tuning, ns)
		# No tuning provided in input file: set to A (E-LAUTE default)
		else:
			tuning = A
	else:
		tuning = args.tuning

	not_type = ''
	if args.type == INPUT:
		# Type provided in input file: set to provided type
		if tab_not_type != None:
			not_type = tab_not_type
		# No type provided in input file: set to FLT (E-LAUTE default)
		else:
			not_type = NOTATIONTYPES[FLT]
	else:
		not_type = NOTATIONTYPES[args.type]

	if args.key == INPUT:
		if args.file.endswith(MEI): # TODO fix
			args.key = "0"
		else:
			args.key = str(_call_java(['java', '-cp', args.classpath, java_path, args.dev, 'key', tuning, args.file]))

	# Adapt
	if args.tablature == YES:
		n = tab_staffDef.get('n')
		lines = tab_staffDef.get('lines')

		# Reset <staffDef> attributes
		tab_staffDef.set('n', str(int(n) + (1 if args.staff == SINGLE else 2)))
		if not_type != NOTATIONTYPES[GLT]:
			tab_staffDef.set('lines', '5' if lines == '5' and not_type == NOTATIONTYPES[FLT] else '6')
			tab_staffDef.set('notationtype', not_type)
		# Reset <tuning>
		# <tuning> is only used in first staffDef, not in those for any subsequent <section>s 
		if is_first_scoreDef:
			tab_tuning.clear()
			tab_tuning.set(XML_ID_KEY, add_unique_id('t', xml_ids)[-1])
			for i, (pitch, octv) in enumerate(TUNINGS[tuning]):
				course = ET.SubElement(tab_tuning, f'{URI_MEI}course',
								   	   **{f'{XML_ID_KEY}': add_unique_id('c', xml_ids)[-1]},
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
							 **{f'{XML_ID_KEY}': add_unique_id('sg', xml_ids)[-1]})
	if args.staff == DOUBLE:
		nh_staffGrp.set('symbol', 'bracket')
		nh_staffGrp.set('bar.thru', 'true')
	staffGrp.insert(0, nh_staffGrp)
	# Add <staffDef>(s)
	for i in [1] if args.staff == SINGLE else [1, 2]:
		nh_staffDef = ET.SubElement(nh_staffGrp, f'{URI_MEI}staffDef',
									**{f'{XML_ID_KEY}': add_unique_id('sd', xml_ids)[-1]},
									n=str(i),
									lines='5'
								   )
		if i == 1:
			nh_staffDef.set('dir.dist', '4')
		# Add <clef>
		# <clef> is only used in first staffDef, not in those for any subsequent <section>s
		if is_first_scoreDef:
			if args.staff == SINGLE:
				clef = _create_element(f'{URI_MEI}clef', 
									   parent=nh_staffDef, 
									   atts=[(XML_ID_KEY, add_unique_id('c', xml_ids)[-1]),
									   		 ('shape', 'G'), 
											 ('line', '2'),
											 ('dis', '8'), 
											 ('dis.place', 'below')]
								  	  )
			else:
				clef = ET.SubElement(nh_staffDef, f'{URI_MEI}clef', 
									 **{f'{XML_ID_KEY}': add_unique_id('c', xml_ids)[-1]},
									 shape='G' if i==1 else 'F',
									 line='2' if i==1 else '4'
									)
		# Add <keySig>
		# <keySig> is only used in first staffDef, not in those for any subsequent <section>s
		# NB Theoretically, the <section> could be in a different key -- but currently a single key 
		#    is assumed for the whole piece
		if is_first_scoreDef:
			keySig = ET.SubElement(nh_staffDef, f'{URI_MEI}keySig',
								   **{f'{XML_ID_KEY}': add_unique_id('ks', xml_ids)[-1]},
								   sig=_get_MEI_keysig(args.key),
								   mode='minor' if args.mode == MINOR else 'major'
								  )
		# Add <meterSig> or <mensur>
		if tab_meterSig is not None:
			nh_meterSig = copy.deepcopy(tab_meterSig)
			nh_meterSig.set(XML_ID_KEY, add_unique_id('ms', xml_ids)[-1])
			nh_staffDef.append(nh_meterSig)
		elif tab_mensur is not None:
			nh_mensur = copy.deepcopy(tab_mensur)
			nh_mensur.set(XML_ID_KEY, add_unique_id('m', xml_ids)[-1])
			nh_staffDef.append(nh_mensur)


def _get_MEI_keysig(key: str): # -> str:
	if key == INPUT:
		return str(0)
	else:
		return key + 's' if int(key) > 0 else str(abs(int(key))) + 'f'


def handle_section(section: ET.Element, ns: dict, args: argparse.Namespace): # -> None
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

	grids_dict = _call_java(['java', '-cp', args.classpath, java_path, args.dev, 'grids', args.key, args.mode])
	mpcGrid = grids_dict['mpcGrid'] # list
	mpcGridStr = str(mpcGrid)
	altGrid = grids_dict['altGrid'] # list
	altGridStr = str(altGrid)
	pcGrid = grids_dict['pcGrid'] # list
	pcGridStr = str(pcGrid)

	tab_notes_by_ID = {}
	tabGrps_by_ID = {}

	if add_accid_ges:
		key_sig_accid_type = 'f' if int(args.key) <= 0 else 's'
		# Key sig accidentals as MIDI pitch classes (e.g. 10, 3)
		key_sig_accid_mpc = [mpcGrid[i] for i in range(len(altGrid)) if altGrid[i] == key_sig_accid_type]

	for measure in section.iter(f'{URI_MEI}measure'):
		# 0. Collect any non-regular elements in <measure> and remove them from it
		regular_elements = [URI_MEI + t for t in ['measure', 'staff', 'layer', 'beam', 'tabGrp', 'tabDurSym', 'note', 'rest']]
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
		tab_staff.set('n', str(int(tab_staff.attrib['n']) + (1 if args.staff == SINGLE else 2)))
		tab_layer = tab_staff.find('mei:layer', ns)
		# Remove
		if args.tablature == NO:
			measure.remove(tab_staff)

		# b. Notehead <staff>s 
		# Add <staff>s to <measure>
		nh_staff_1 = ET.Element(f'{URI_MEI}staff', 
								**{f'{XML_ID_KEY}': add_unique_id('s', xml_ids)[-1]},
								n='1')
		nh_staff_2 = ET.Element(f'{URI_MEI}staff', 
								**{f'{XML_ID_KEY}': add_unique_id('s', xml_ids)[-1]},
								n='2')
		measure.insert(0, nh_staff_1)
		if args.staff == DOUBLE:
			measure.insert(1, nh_staff_2)

		# Add <layer>s to <staff>s
		nh_layer_1 = ET.SubElement(nh_staff_1, f'{URI_MEI}layer', 
								   **{f'{XML_ID_KEY}': add_unique_id('l', xml_ids)[-1]},
								   n='1')
		nh_layer_2 = ET.SubElement(nh_staff_2, f'{URI_MEI}layer', 
								   **{f'{XML_ID_KEY}': add_unique_id('l', xml_ids)[-1]},
								   n='1')

		# Add <rest>s, and <chord>s and/or<space>s to <layer>s; collect <dir>s
		dirs = []
		accidsInEffect = [[], [], [], [], []] # double flats, flats, naturals, sharps, double sharps
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
				xml_id_rest_1 = add_unique_id('r', xml_ids)[-1]
				xml_id_rest_2 = add_unique_id('r', xml_ids)[-1]

				# 1. Add <rest>s to <layer>s
				rest_1 = _create_element(f'{URI_MEI}rest', 
										 parent=nh_layer_1, 
										 atts=[(XML_ID_KEY, xml_id_rest_1),
										 	   ('dur', dur)]
										)
				rest_2 = _create_element(f'{URI_MEI}rest', 
										 parent=nh_layer_2, 
										 atts=[(XML_ID_KEY, xml_id_rest_2),
										 	   ('dur', dur)]
										)

				# 2. Add <dir>
				dirs.append(_make_dir(xml_id_rest_1, dur, dots, ns))

				# 3. Map tabGrp
				rests = (rest_1, None) if args.staff == SINGLE else (rest_1, rest_2)
				tabGrps_by_ID[xml_id_tabGrp] = (tabGrp, rests)
				# Map tab <rest>
				if rest != None:
					tab_notes_by_ID[rest.get(XML_ID_KEY)] = (rest, rests) 

			# Add <chord>s and/or <space>s	
			else:
				# 0. Create <chord>s and add <note>s to them
				# NB A <chord> cannot be added directly to the parent <layer> upon creation 
				#    because it may remain empty, and in that case must be replaced by a <space>
				xml_id_chord_1 = add_unique_id('c', xml_ids)[-1]
				xml_id_chord_2 = add_unique_id('c', xml_ids)[-1]
				chord_1 = _create_element(f'{URI_MEI}chord', 
										  atts=[(XML_ID_KEY, xml_id_chord_1),
										   		('dur', dur), 
										   		('stem.visible', 'false')]
										 )
				chord_2 = _create_element(f'{URI_MEI}chord', 
										  atts=[(XML_ID_KEY, xml_id_chord_2),
										   		('dur', dur), 
										   		('stem.visible', 'false')]
										 )
				for element in tabGrp:
					if element != flag and element != rest and element != space:
						try:
							midi_pitch = _get_midi_pitch(int(element.get('tab.course')), 
													 	 int(element.get('tab.fret')), 
													 	 tuning)
						except TypeError:
							raise Exception(f"Element {element.tag} with attributes\
											{element.attrib} is either missing tab.course or tab.fret")

						midi_pitch_class = midi_pitch % 12
						# a. The note is in key	and there are no accidentals in effect
						if midi_pitch_class in mpcGrid and not any(accidsInEffect):
							pname = pcGrid[mpcGrid.index(midi_pitch_class)]
							accid = ''									
							if add_accid_ges:
								accid_ges = key_sig_accid_type if midi_pitch_class in key_sig_accid_mpc else ''
						# b. The note is in key	and there are accidentals in effect / the note is not in key
						else:
							cmd = ['java', '-cp', args.classpath, java_path, args.dev, 'pitch', str(midi_pitch), 
									args.key, mpcGridStr, altGridStr, pcGridStr, str(accidsInEffect)]
							spell_dict = _call_java(cmd)
							pname = spell_dict['pname'] # str
							accid = spell_dict['accid'] # str
							if add_accid_ges:
								accid_ges = spell_dict['accid.ges'] # str
							accidsInEffect = spell_dict['accidsInEffect'] # list
						accid_part = [('accid', accid)] if accid != '' else []
						if add_accid_ges:
							# accid.ges overrules accid
							if accid_ges != '':
								accid_part = [('accid.ges', accid_ges)]

						xml_id_note = add_unique_id('n', xml_ids)[-1]
						nh_note = _create_element(f'{URI_MEI}note', 
												  parent=chord_1 if args.staff == SINGLE else\
												         (chord_1 if midi_pitch >= 60 else chord_2), 
												  atts=[(XML_ID_KEY, xml_id_note),
												  		('pname', pname),
												        ('oct', str(_get_octave(midi_pitch))),
												   		('head.fill', 'solid')] + (accid_part)
											 	 )
						# Map tab <note>
						tab_notes_by_ID[element.get(XML_ID_KEY)] = (element, nh_note)

				# 1. Add <chord>s and/or <space>s to <layer>s
				xml_id_space = add_unique_id('s', xml_ids)[-1]
				nh_space = _create_element(f'{URI_MEI}space', 
										   atts=[(XML_ID_KEY, xml_id_space),
												 ('dur', dur)]
										  )
				nh_layer_1.append(chord_1 if len(chord_1) > 0 else nh_space)
				if args.staff == DOUBLE:
					nh_layer_2.append(chord_2 if len(chord_2) > 0 else nh_space)
				xml_id_reference = xml_id_chord_1 if len(chord_1) > 0 else xml_id_space

				# 2. Add <dir>
				if flag != None:
					dirs.append(_make_dir(xml_id_reference, dur, dots, ns))

				# 3. Map tabGrp
				chords = (chord_1, None) if args.staff == SINGLE\
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
				xml_id_tabGrp = c.get('startid')[1:] # start after '#'
				xml_id_upper_chord = tabGrps_by_ID[xml_id_tabGrp][1][0].get(XML_ID_KEY)
				dirs.append(_make_dir(xml_id_upper_chord, 'f', None, ns))

				# Add to list	
				if args.tablature == YES:
					curr_non_regular_elements.append(c)
			# Annotation: needs <annot> (CMN) and <annot> (= c; tab) 
			elif c.tag == f'{URI_MEI}annot':
				# Make <annot> for CMN
				xml_id_tab_note = c.get('plist')[1:] # start after '#'
				xml_id_note = tab_notes_by_ID[xml_id_tab_note][1].get(XML_ID_KEY)
				annot = copy.deepcopy(c)
				annot.set('plist', '#' + xml_id_note)
				annot.set(XML_ID_KEY, add_unique_id('a', xml_ids)[-1])

				# Add to list
				curr_non_regular_elements.append(annot)
				if args.tablature == YES:
					curr_non_regular_elements.append(c)
			# Fingering: needs <fing> (= c; tab)
			elif c.tag == f'{URI_MEI}fing':
				# Add to list
				if args.tablature == YES:
					curr_non_regular_elements.append(c)

		# 3. Add non-regular <measure> elements to completed <measure> in fixed sequence
		fermatas = [e for e in curr_non_regular_elements if e.tag == f'{URI_MEI}fermata']
		annots = [e for e in curr_non_regular_elements if e.tag == f'{URI_MEI}annot']
		fings = [e for e in curr_non_regular_elements if e.tag == f'{URI_MEI}fing']
		for e in dirs + fermatas + annots + fings:
			measure.append(e)

		if verbose:
			for elem in measure:
				print(elem.tag, elem.attrib)
				for e in elem:
					print(e.tag, e.attrib)
					for ee in e:
						print(ee.tag, ee.attrib)
						for eee in ee:
							print(eee.tag, eee.attrib)


def _make_dir(xml_id: str, dur: int, dots: int, ns: dict): # -> 'ET.Element'
	d = ET.Element(f'{URI_MEI}dir', 
				   **{f'{XML_ID_KEY}': add_unique_id('d', xml_ids)[-1]},
				   place='above', 
				   startid='#' + xml_id
				  )
	
	# Non-fermata case
	if dur != 'f':
		_create_element(f'{URI_MEI}symbol', 
						parent=d, 
						atts=[(XML_ID_KEY, add_unique_id('s', xml_ids)[-1]),
							  ('glyph.auth', 'smufl'), 
							  ('glyph.name', SMUFL_LUTE_DURS[int(dur)])]
				   	   )
		if dots != None:
			_create_element(f'{URI_MEI}symbol', 
							parent=d, 
							atts=[(XML_ID_KEY, add_unique_id('s', xml_ids)[-1]),
								  ('glyph.auth', 'smufl'), 
							 	  ('glyph.name', SMUFL_LUTE_DURS['.'])]
						   )
	# Fermata case 
	else:
		_create_element(f'{URI_MEI}symbol', 
						parent=d, 
						atts=[(XML_ID_KEY, add_unique_id('s', xml_ids)[-1]),
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


def transcribe(infile: str, arg_paths: dict, args: argparse.Namespace): # -> None
	inpath = arg_paths['inpath']
	outpath = arg_paths['outpath']

	filename, ext = os.path.splitext(os.path.basename(infile)) # input file name, extension
	outfile = filename + '-dipl' + MEI # output file
	args.file = infile # NB already the case when using -f

	# Get file contents as MEI string
	if ext != MEI:
		# As in abtab converter: provide three opts, always with their default vals, and no user opts
		opts_java = '-u -t -y -h'
		default_vals_java = 'i y i n/a' 
		user_opts_vals_java = ''
		cmd = ['java', '-cp', args.classpath, java_path_conv, args.dev, opts_java, default_vals_java,\
			   user_opts_vals_java, 'false', infile, filename + MEI]
		res = _call_java(cmd)
		mei_str = res['content']
	else:
		with open(os.path.join(inpath, infile), 'r', encoding='utf-8') as file:
			mei_str = file.read()

	# TODOs
	# - in handle_scoreDef(), instead of using tuning and not_type, reassign args.tuning and args.type (or do it here,
	#   before handle_scoreDef() is called) (?)

	# Handle namespaces
	ns = handle_namespaces(mei_str)
	global URI_MEI
	URI_MEI = f'{{{ns['mei']}}}'
	global URI_XML
	URI_XML = f'{{{ns['xml']}}}'
	global XML_ID_KEY
	XML_ID_KEY = f'{URI_XML}id'

	# Get the tree, root (<mei>), and main MEI elements (<meiHead>, <score>)
	tree, root = parse_tree(mei_str)
	meiHead, music = get_main_MEI_elements(root, ns)
#	meiHead = root.find('mei:meiHead', ns)
#	music = root.find('mei:music', ns)
	score = music.find('.//mei:score', ns)

	# Collect all xml:ids
	global xml_ids
	xml_ids = collect_xml_ids(root, XML_ID_KEY)
#	xml_ids = [elem.attrib[XML_ID_KEY] for elem in root.iter() if XML_ID_KEY in elem.attrib]

	# Handle <scoreDef>s
	scoreDefs = score.findall('.//mei:scoreDef', ns)
	for scoreDef in scoreDefs:
		handle_scoreDef(scoreDef, ns, args)

	# Handle <section>s
	sections = score.findall('mei:section', ns)
	for section in sections:
		handle_section(section, ns, args)

	# Fix indentation
	ET.indent(tree, space='\t', level=0)

	# Add processing instructions (<?xml> declaration and <?xml-model> processing 
	# instructions), which are not included in root, and write to file 
	lines = mei_str.split('\n')
	declaration = lines[0] + '\n'
	model_pi = ''
	for line in lines:
		if line[1:].startswith('?xml-model'):
			model_pi += line + '\n'
	xml_str = ET.tostring(root, encoding='unicode')
	xml_str = f'{declaration}{model_pi}{xml_str}'
	with open(os.path.join(outpath, outfile), 'w', encoding='utf-8') as file:
		file.write(xml_str)
