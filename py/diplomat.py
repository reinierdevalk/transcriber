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
  - use get('<att_name>') to get an element's attribute
  - use find() to find first direct child element
  - use findall() with XPath to find first recursive child element. See 
    https://docs.python.org/3/library/xml.etree.elementtree.html#elementtree-xpath
- namespaces
  - element namespaces: the namespace dict is mostly useful for element searches (find(), findall())
  - attribute namespaces: need to be provided explicitly in the get(), or constructed from the namespace dict

"""

import argparse
import copy
import json
import os.path
import random
import string
import subprocess
import xml.etree.ElementTree as ET
from subprocess import Popen, PIPE, run
from parser_vals import *

notationtypes = {FLT: 'tab.lute.french',
				 ILT: 'tab.lute.italian',
				 SLT: 'tab.lute.spanish',
				 GLT: 'tab.lute.german'
				}
tunings = {F   : [('f', 4), ('c', 4), ('g', 3), ('eb', 3), ('bb', 2), ('f', 2)],
		   F6Eb: [('f', 4), ('c', 4), ('g', 3), ('eb', 3), ('bb', 2), ('eb', 2)],
		   G   : [('g', 4), ('d', 4), ('a', 3), ('f', 3), ('c', 3), ('g', 2)], 
		   G6F : [('g', 4), ('d', 4), ('a', 3), ('f', 3), ('c', 3), ('f', 2)], 
		   A   : [('a', 4), ('e', 4), ('b', 3), ('g', 3), ('d', 3), ('a', 2)], 
		   A6G : [('a', 4), ('e', 4), ('b', 3), ('g', 3), ('d', 3), ('g', 2)]
		  }
shift_intervals = {F: -2, F6Eb: -2, G: 0, G6F: 0, A: 2, A6G: 2}
smufl_lute_durs = {'f': 'fermataAbove',
				   1: 'luteDurationDoubleWhole',
				   2: 'luteDurationWhole',
				   4: 'luteDurationHalf', 
				   8: 'luteDurationQuarter',
				   16: 'luteDuration8th',
				   32: 'luteDuration16th',
				   '.': 'augmentationDot'
				  }

java_path = 'tools.music.PitchKeyTools' # <package>.<package>.<file>
java_path_conv = 'tbp.editor.Editor' # <package>.<package>.<file>
verbose = False
add_accid_ges = True

xml_ids = []
tuning = ''
LEN_ID = 8


def _add_unique_id(prefix, arg_xml_ids):
	"""
	Generates a unique ID with the given prefix and adds it to given list.

	Args:
		prefix (str): The prefix for the ID.
		arg_xml_ids (list): The list of existing IDs.

	Returns:
		list: The updated list of IDs.
	"""
	while True:
		rand_id = ''.join(random.choices(string.ascii_letters + string.digits, k=(LEN_ID - len(prefix))))
		xml_id = prefix + rand_id
		if xml_id not in arg_xml_ids:
			arg_xml_ids.append(xml_id)
			break

	return arg_xml_ids


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


def handle_namespaces(path: str): # -> dict
	# There is only one namespace, whose key is an empty string -- replace the  
	# key with something meaningful ('mei'). See
	# https://stackoverflow.com/questions/42320779/get-the-namespaces-from-xml-with-python-elementtree/42372404#42372404
	# To avoid an 'ns0' prefix before each tag, register the namespace as an empty string. See
	# https://stackoverflow.com/questions/8983041/saving-xml-files-using-elementtree
	ns = dict([node for _, node in ET.iterparse(path, events=['start-ns'])])
	ns['mei'] = ns.pop('')
	ET.register_namespace('', ns['mei'])
	ns['xml'] = 'http://www.w3.org/XML/1998/namespace'

	return ns


def parse_tree(path: str): # -> Tuple
	"""
	Basic structure of <mei>:
	
	<mei> 
	  <meiHead/>
	  <music>
	    ...
	    <score>
	      <scoreDef/>
	      <section/>
	    </score>
	  </music>
	</mei>   
	"""
	tree = ET.parse(path)
	root = tree.getroot()

	return (tree, root)


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

	uri_mei = f'{{{ns['mei']}}}'
	uri_xml = f'{{{ns['xml']}}}'
	xml_id_key = f'{uri_xml}id'

	staffGrp = scoreDef.find('mei:staffGrp', ns)

	# 1. Tablature <staffDef>: adapt or remove  
	tab_staffDef = staffGrp.find('mei:staffDef', ns)
	tab_meterSig = tab_staffDef.find('mei:meterSig', ns)
	tab_mensur = tab_staffDef.find('mei:mensur', ns)
	tab_tuning = tab_staffDef.find('mei:tuning', ns)
	tab_not_type = tab_staffDef.get('notationtype')

	global tuning
	if args.tuning == INPUT:
		# Tuning provided in input file: set to provided tuning
		if tab_tuning != None:
			tuning_p_o = [(c.get('pname'), int(c.get('oct'))) for c in tab_tuning.findall(uri_mei + 'course', ns)]
			tuning = next((k for k, v in tunings.items() if v == tuning_p_o), None)
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
			not_type = notationtypes[FLT]
	else:
		not_type = notationtypes[args.type]

	if args.key == INPUT:
		args.key = "-1"
#		args.key = _call_java(['java', '-cp', args.classpath, java_path, args.dev, 'key', tuning, args.file])

	# Adapt
	if args.tablature == YES:
		n = tab_staffDef.get('n')
		lines = tab_staffDef.get('lines')

		# Reset <staffDef> attributes
		tab_staffDef.set('n', str(int(n) + (1 if args.staff == SINGLE else 2)))
		if not_type != notationtypes[GLT]:
			tab_staffDef.set('lines', '5' if lines == '5' and not_type == notationtypes[FLT] else '6')
			tab_staffDef.set('notationtype', not_type)
		# Reset <tuning>	
		tab_tuning.clear()
		tab_tuning.set(xml_id_key, _add_unique_id('t', xml_ids)[-1])
		for i, (pitch, octv) in enumerate(tunings[tuning]):
			course = ET.SubElement(tab_tuning, uri_mei + 'course',
								   **{f'{xml_id_key}': _add_unique_id('c', xml_ids)[-1]},
								   n=str(i+1),
								   pname=pitch[0],
								   oct=str(octv),
								   accid='' if len(pitch) == 1 else ('f' if pitch[1] == 'b' else 's')
								  )
	# Remove
	else:
		staffGrp.remove(tab_staffDef)

	# 2. Notehead <staffGrp>: create and set as first element in <staffGrp>
	nh_staffGrp = ET.Element(uri_mei + 'staffGrp', 
							 **{f'{xml_id_key}': _add_unique_id('sg', xml_ids)[-1]})
	if args.staff == DOUBLE:
		nh_staffGrp.set('symbol', 'bracket')
		nh_staffGrp.set('bar.thru', 'true')
	staffGrp.insert(0, nh_staffGrp)
	# Add <staffDef>(s)
	for i in [1] if args.staff == SINGLE else [1, 2]:
		nh_staffDef = ET.SubElement(nh_staffGrp, uri_mei + 'staffDef',
									**{f'{xml_id_key}': _add_unique_id('sd', xml_ids)[-1]},
									n=str(i),
									lines='5'
								   )
		if i == 1:
			nh_staffDef.set('dir.dist', '4')
		# Add <clef>
		if args.staff == SINGLE:
			clef = _create_element(uri_mei + 'clef', 
								   parent=nh_staffDef, 
								   atts=[(xml_id_key, _add_unique_id('c', xml_ids)[-1]),
								   		 ('shape', 'G'), 
										 ('line', '2'),
										 ('dis', '8'), 
										 ('dis.place', 'below')]
								  )
		else:
			clef = ET.SubElement(nh_staffDef, uri_mei + 'clef', 
								 **{f'{xml_id_key}': _add_unique_id('c', xml_ids)[-1]},
								 shape='G' if i==1 else 'F',
								 line='2' if i==1 else '4'
								)
		# Add <keySig>
		keySig = ET.SubElement(nh_staffDef, uri_mei + 'keySig',
							   **{f'{xml_id_key}': _add_unique_id('ks', xml_ids)[-1]},
							   sig=_get_MEI_keysig(args.key),
							   mode='minor' if args.mode == MINOR else 'major'
							  )
		# Add <meterSig> or <mensur>
		if tab_meterSig is not None:
			nh_meterSig = copy.deepcopy(tab_meterSig)
			nh_meterSig.set(xml_id_key, _add_unique_id('ms', xml_ids)[-1])
			nh_staffDef.append(nh_meterSig)
		elif tab_mensur is not None:
			nh_mensur = copy.deepcopy(tab_mensur)
			nh_mensur.set(xml_id_key, _add_unique_id('m', xml_ids)[-1])
			nh_staffDef.append(nh_mensur)


def _get_MEI_keysig(key: str): # -> str:
	if key == INPUT:
		return str(0)
	else:
		return key + 's' if int(key) > 0 else str(abs(int(key))) + 'f'
#		return str(key) + 's' if key > 0 else str(abs(key)) + 'f'


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

	uri_mei = f'{{{ns['mei']}}}'
	uri_xml = f'{{{ns['xml']}}}'
	xml_id_key = f'{uri_xml}id'

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

	for measure in section.iter(uri_mei + 'measure'):
		# 0. Collect any non-regular elements in <measure> and remove them from it
		regular_elements = [uri_mei + t for t in ['measure', 'staff', 'layer', 'tabGrp', 'tabDurSym', 'note', 'rest']]
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
		nh_staff_1 = ET.Element(uri_mei + 'staff', 
								**{f'{xml_id_key}': _add_unique_id('s', xml_ids)[-1]},
								n='1')
		nh_staff_2 = ET.Element(uri_mei + 'staff', 
								**{f'{xml_id_key}': _add_unique_id('s', xml_ids)[-1]},
								n='2')
		measure.insert(0, nh_staff_1)
		if args.staff == DOUBLE:
			measure.insert(1, nh_staff_2)

		# Add <layer>s to <staff>s
		nh_layer_1 = ET.SubElement(nh_staff_1, uri_mei + 'layer', 
								   **{f'{xml_id_key}': _add_unique_id('l', xml_ids)[-1]},
								   n='1')
		nh_layer_2 = ET.SubElement(nh_staff_2, uri_mei + 'layer', 
								   **{f'{xml_id_key}': _add_unique_id('l', xml_ids)[-1]},
								   n='1')

		# Add <rest>s, and <chord>s and/or<space>s to <layer>s; collect <dir>s
		dirs = []
		accidsInEffect = [[], [], [], [], []] # double flats, flats, naturals, sharps, double sharps
		for tabGrp in tab_layer.iter(uri_mei + 'tabGrp'):
			dur = tabGrp.get('dur')
			dots = tabGrp.get('dots')
			flag = tabGrp.find('mei:tabDurSym', ns)
			rest = tabGrp.find('mei:rest', ns)
			space = tabGrp.find('mei:space', ns)
			xml_id_tabGrp = tabGrp.get(xml_id_key)

			# Add <rest>s. Rests can be implicit (a <tabGrp> w/ only a <tabDurSym>) or
			# explicit (a <tabGrp> w/ a <rest> (and possibly a <tabDurSym>)). Both are
			# transcribed as a <rest> in the CMN
			if (flag != None and (len(tabGrp) == 1) or rest != None): # or space != None):
				xml_id_rest_1 = _add_unique_id('r', xml_ids)[-1]
				xml_id_rest_2 = _add_unique_id('r', xml_ids)[-1]

				# 1. Add <rest>s to <layer>s
				rest_1 = _create_element(uri_mei + 'rest', 
										 parent=nh_layer_1, 
										 atts=[(xml_id_key, xml_id_rest_1),
										 	   ('dur', dur)]
										)
				rest_2 = _create_element(uri_mei + 'rest', 
										 parent=nh_layer_2, 
										 atts=[(xml_id_key, xml_id_rest_2),
										 	   ('dur', dur)]
										)

				# 2. Add <dir>
				dirs.append(_make_dir(xml_id_rest_1, dur, dots, ns))

				# 3. Map tabGrp
				rests = (rest_1, None) if args.staff == SINGLE else (rest_1, rest_2)
				tabGrps_by_ID[xml_id_tabGrp] = (tabGrp, rests)
				# Map tab <rest>
				if rest != None:
					tab_notes_by_ID[rest.get(xml_id_key)] = (rest, rests) 

			# Add <chord>s and/or <space>s	
			else:
				# 0. Create <chord>s and add <note>s to them
				# NB A <chord> cannot be added directly to the parent <layer> upon creation 
				#    because it may remain empty, and in that case must be replaced by a <space>
				xml_id_chord_1 = _add_unique_id('c', xml_ids)[-1]
				xml_id_chord_2 = _add_unique_id('c', xml_ids)[-1]
				chord_1 = _create_element(uri_mei + 'chord', 
										  atts=[(xml_id_key, xml_id_chord_1),
										   		('dur', dur), 
										   		('stem.visible', 'false')]
										 )
				chord_2 = _create_element(uri_mei + 'chord', 
										  atts=[(xml_id_key, xml_id_chord_2),
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

						xml_id_note = _add_unique_id('n', xml_ids)[-1]
						nh_note = _create_element(uri_mei + 'note', 
												  parent=chord_1 if args.staff == SINGLE else\
												         (chord_1 if midi_pitch >= 60 else chord_2), 
												  atts=[(xml_id_key, xml_id_note),
												  		('pname', pname),
												        ('oct', str(_get_octave(midi_pitch))),
												   		('head.fill', 'solid')] + (accid_part)
											 	 )
						# Map tab <note>
						tab_notes_by_ID[element.get(xml_id_key)] = (element, nh_note)

				# 1. Add <chord>s and/or <space>s to <layer>s
				xml_id_space = _add_unique_id('s', xml_ids)[-1]
				nh_space = _create_element(uri_mei + 'space', 
										   atts=[(xml_id_key, xml_id_space),
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
			if c.tag == uri_mei + 'fermata':
				# Make <dir> for CMN and add 
				xml_id_tabGrp = c.get('startid')[1:] # start after '#'
				xml_id_upper_chord = tabGrps_by_ID[xml_id_tabGrp][1][0].get(xml_id_key)
				dirs.append(_make_dir(xml_id_upper_chord, 'f', None, ns))

				# Add to list	
				if args.tablature == YES:
					curr_non_regular_elements.append(c)
			# Annotation: needs <annot> (CMN) and <annot> (= c; tab) 
			elif c.tag == uri_mei + 'annot':
				# Make <annot> for CMN
				xml_id_tab_note = c.get('plist')[1:] # start after '#'
				xml_id_note = tab_notes_by_ID[xml_id_tab_note][1].get(xml_id_key)
				annot = copy.deepcopy(c)
				annot.set('plist', '#' + xml_id_note)
				annot.set(xml_id_key, _add_unique_id('a', xml_ids)[-1])

				# Add to list
				curr_non_regular_elements.append(annot)
				if args.tablature == YES:
					curr_non_regular_elements.append(c)
			# Fingering: needs <fing> (= c; tab)
			elif c.tag == uri_mei + 'fing':
				# Add to list
				if args.tablature == YES:
					curr_non_regular_elements.append(c)

		# 3. Add non-regular <measure> elements to completed <measure> in fixed sequence
		fermatas = [e for e in curr_non_regular_elements if e.tag == uri_mei + 'fermata']
		annots = [e for e in curr_non_regular_elements if e.tag == uri_mei + 'annot']
		fings = [e for e in curr_non_regular_elements if e.tag == uri_mei + 'fing']
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


# NB For debugging: set, where this function is called, use_Popen=True.
#    - output is what the stdout (System.out.println()) printouts from Java return;
#      it is passed to json.loads() and must be formatted as json
#    - errors is what the stderr (System.err.println()) debugging printouts from
#      Java return; it is printed when use_Popen=True and doesn't have to be formatted
def _call_java(cmd: list, use_Popen: bool=False): # -> dict:
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
		outp = process.stdout # bytes
#		print(outp)

	return json.loads(outp)


def _make_dir(xml_id: str, dur: int, dots: int, ns: dict): # -> 'ET.Element'
	uri_mei = f'{{{ns['mei']}}}'
	uri_xml = f'{{{ns['xml']}}}'
	xml_id_key = f'{uri_xml}id'

	d = ET.Element(uri_mei + 'dir', 
				   **{f'{xml_id_key}': _add_unique_id('d', xml_ids)[-1]},
				   place='above', 
				   startid='#' + xml_id
				  )
	
	# Non-fermata case
	if dur != 'f':
		_create_element(uri_mei + 'symbol', 
						parent=d, 
						atts=[(xml_id_key, _add_unique_id('s', xml_ids)[-1]),
							  ('glyph.auth', 'smufl'), 
							  ('glyph.name', smufl_lute_durs[int(dur)])]
				   	   )
		if dots != None:
			_create_element(uri_mei + 'symbol', 
							parent=d, 
							atts=[(xml_id_key, _add_unique_id('s', xml_ids)[-1]),
								  ('glyph.auth', 'smufl'), 
							 	  ('glyph.name', smufl_lute_durs['.'])]
						   )
	# Fermata case 
	else:
		_create_element(uri_mei + 'symbol', 
						parent=d, 
						atts=[(xml_id_key, _add_unique_id('s', xml_ids)[-1]),
							  ('glyph.auth', 'smufl'), 
						 	  ('glyph.name', smufl_lute_durs['f'])]
				   	   )

	return d


def _get_midi_pitch(course: int, fret: int, tuning: str): # -> int:
	# Determine the MIDI pitches for the open courses
	abzug = 0 if not '-' in tuning else 2
	open_courses = [67, 62, 57, 53, 48, (43 - abzug)]
	if tuning[0] != G:
		shift_interv = shift_intervals[tuning[0]]
		open_courses = list(map(lambda x: x+shift_interv, open_courses))
	return open_courses[course-1] + fret


def _get_octave(midi_pitch: int): # -> int:
	c = midi_pitch - (midi_pitch % 12)
	return int((c / 12) - 1)


def transcribe(infiles: list, arg_paths: dict, args: argparse.Namespace): # -> None
	inpath = arg_paths['inpath']
	outpath = arg_paths['outpath']

	for infile in infiles:
		filename, ext = os.path.splitext(os.path.basename(infile)) # input file name, extension
		outfile = filename + '-dipl' + ext # output file

		xml_file = os.path.join(inpath, infile)

		# If not an .mei file: convert
		if ext != MEI:
			# As in abtab converter: provide three opts, always with their default vals, and no user opts
			opts_java = '-u -t -y -h'
			default_vals_java = 'i y i n/a' 
			user_opts_vals_java = ''
			cmd = ['java', '-cp', args.classpath, java_path_conv, args.dev, opts_java, default_vals_java,\
				   user_opts_vals_java, 'false', infile, filename + MEI]
			mei_str = _call_java(cmd)

#			print('- - - - -')
#			print(mei_str['content'])
#			hihihihih

		# TODOs
		# - resolve comments in abtab (all the way down, at 'elif [ "$TOOL" == "transcriber" ]; then)'
		# - figure out how parseCLIArgs(), setPieceSpecificTransParams(), getTranscriptionParams(), convertToTbp(),
		#   ... are used together in java
		# - issue with utils/utility repo on GitHub
		#
		# - fix _call_java() 'key' version --> give it args.file as arg and make mei-tbp conversion in TabImport to
		#   extract .tbp in PitchKeyTools
		# - use mei_str (instead of xml_file) to extract PIs; use mei_str as arg to handle_namespaces() and parse_tree()  
		# - in handle_scoreDef(), instead of using tuning and not_type, reassign args.tuning and args.type (or do it here,
		#   before handle_scoreDef() is called) (?)

		# Manually extract processing instructions (PIs): <?xml> declaration and <?xml-model> PI 
		with open(xml_file, 'r', encoding='utf-8') as file:
			content = file.read()
#			print('- - - - - -')
#			print(content)
#			print('- - - - - -')
#			dsfdsf
			lines = content.split('\n')
			declaration = lines[0] + '\n'
			if lines[1][1:].startswith('?xml-model'):
				model_pi = lines[1] + '\n'
			else:
				model_pi = ''

		# Handle namespaces
		ns = handle_namespaces(xml_file)
		uri = '{' + ns['mei'] + '}'

		# Get the root, tree, and main MEI elements (<meiHead> and <music>);
		# collect all xml:ids
		tree, mei = parse_tree(xml_file)
		meiHead = mei.find('mei:meiHead', ns)
		music = mei.find('mei:music', ns)
		xml_id = f"{{{ns['xml']}}}id"
		global xml_ids
		xml_ids = [elem.attrib[xml_id] for elem in mei.iter() if xml_id in elem.attrib]

		# Handle <scoreDef>
		score = music.findall('.//' + uri + 'score')[0]
		scoreDef = score.find('mei:scoreDef', ns)
		handle_scoreDef(scoreDef, ns, args)

		# Handle <section>
		section = score.find('mei:section', ns)
		handle_section(section, ns, args)

		# Fix indentation
		ET.indent(tree, space='\t', level=0)

#		# Write to file
#		tree.write(os.path.join(outpath, outfile))

		# Prepend declaration and processing instructions
		xml_str = ET.tostring(tree.getroot(), encoding='unicode')
		xml_str = f'{declaration}{model_pi}{xml_str}'
		with open(os.path.join(outpath, outfile), 'w', encoding='utf-8') as file:
			file.write(xml_str)