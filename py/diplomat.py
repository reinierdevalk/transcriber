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
  - use find() to find first direct child element
  - use findall() with XPath to find first recursive child element. See 
    https://docs.python.org/3/library/xml.etree.elementtree.html#elementtree-xpath
- namespaces
  - element namespaces: the namespace dict is mostly useful for element searches (find(), findall())
  - attribute namespaces: need to be provided explicitly in the get(), or constructed from the namespace dict

"""

import argparse
import json
import os.path
import subprocess
import xml.etree.ElementTree as ET
from subprocess import Popen, PIPE, run
import copy

notationtypes = {'FLT': 'tab.lute.french',
				 'ILT': 'tab.lute.italian',
				 'SLT': 'tab.lute.spanish',
				 'GLT': 'tab.lute.german'
				}
tunings = {'F' : [('f', 4), ('c', 4), ('g', 3), ('eb', 3), ('bb', 2), ('f', 2)],
		   'F-': [('f', 4), ('c', 4), ('g', 3), ('eb', 3), ('bb', 2), ('eb', 2)],
		   'G' : [('g', 4), ('d', 4), ('a', 3), ('f', 3), ('c', 3), ('g', 2)], 
		   'G-': [('g', 4), ('d', 4), ('a', 3), ('f', 3), ('c', 3), ('f', 2)], 
		   'A' : [('a', 4), ('e', 4), ('b', 3), ('g', 3), ('d', 3), ('a', 2)], 
		   'A-': [('a', 4), ('e', 4), ('b', 3), ('g', 3), ('d', 3), ('g', 2)]
		  }
shift_intervals = {'F': -2, 'G': 0, 'A': 2}
smufl_lute_durs = {'f': 'fermataAbove',
				   1: 'luteDurationDoubleWhole',
				   2: 'luteDurationWhole',
				   4: 'luteDurationHalf', 
				   8: 'luteDurationQuarter',
				   16: 'luteDuration8th',
				   32: 'luteDuration16th',
				   '.': 'augmentationDot'
				  }
#cp_dirs = [
#		   'formats/lib/*',
#		   'formats/bin/',
#		   'machine_learning/lib/*',
#		   'machine_learning/bin/',
#		   'melody_models/lib/*',
#		   'melody_models/bin/',
#		   'representations/lib/*',
#		   'representations/bin/',
#		   'tabmapper/lib/*',
#		   'tabmapper/bin/',
#		   'utils/lib/*',
#		   'utils/bin/',
#		   'voice_separation/lib/*',
#		   'voice_separation/bin/'
#		  ]
#cp_dirs = [
#		   'formats\\lib\\*',
#		   'formats\\bin\\',
#		   'machine_learning\\lib\\*',
#		   'machine_learning\\bin\\',
#		   'melody_models\\lib\\*',
#		   'melody_models\\bin\\',
#		   'representations\\lib\\*',
#		   'representations\\bin\\',
#		   'tabmapper\\lib\\*',
#		   'tabmapper\\bin\\',
#		   'utils\\lib\\*',
#		   'utils\\bin\\',
#		   'voice_separation\\lib\\*',
#		   'voice_separation\\bin\\'
#		  ]
#
#cp = (':' if os.name == 'posix' else ';').join(cp_dirs)

java_path = 'tools.music.PitchKeyTools' # <package>.<package>.<file>
verbose = False


def _handle_namespaces(path: str): # -> dict
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


def _parse_tree(path: str, ns: dict): # -> Tuple
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
	mei = tree.getroot()
	meiHead = mei.find('mei:meiHead', ns)
	music = mei.find('mei:music', ns)

	return (tree, meiHead, music)


def _handle_scoreDef(scoreDef: ET.Element, ns: dict, args: argparse.Namespace): # -> None
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
	# Adapt
	if args.tablature == 'y':
		n = tab_staffDef.get('n')
		lines = tab_staffDef.get('lines')
		not_type = tab_staffDef.get('notationtype')
		tuning = tab_staffDef.find('mei:tuning', ns)
		# TODO: this is a placeholder -- remove when GLT is ready to use
		if not_type == notationtypes['GLT']:
			not_type = notationtypes['FLT']
			tab_staffDef.attrib.pop('lines.visible', None)
			tab_staffDef.attrib.pop('notationsubtype', None)
			tab_staffDef.attrib.pop('valign', None)
		# Reset <staffDef> attributes
		tab_staffDef.set('n', str(int(n) + (1 if args.staff == 's' else 2)))
		if not_type != notationtypes['GLT']:
			tab_staffDef.set('lines', '5' if lines == '5' and args.type == 'FLT' else '6')
			tab_staffDef.set('notationtype', notationtypes[args.type])
		# Reset <tuning>	
		tuning.clear()
		for i, (pitch, octv) in enumerate(tunings[args.tuning]):
			course = ET.SubElement(tuning, uri_mei + 'course',
								   n=str(i+1),
								   pname=pitch[0],
								   oct=str(octv),
								   accid='' if len(pitch) == 1 else ('f' if pitch[1] == 'b' else 's')
								  )
	# Remove
	else:
		staffGrp.remove(tab_staffDef)

	# 2. Notehead <staffGrp>: create and set as first element in <staffGrp>
	nh_staffGrp = ET.Element(uri_mei + 'staffGrp')
	if args.staff == 'd':
		nh_staffGrp.set('symbol', 'bracket')
		nh_staffGrp.set('bar.thru', 'true')
	staffGrp.insert(0, nh_staffGrp)
	# Add <staffDef>(s)
	for i in [1] if args.staff == 's' else [1, 2]:
		nh_staffDef = ET.SubElement(nh_staffGrp, uri_mei + 'staffDef',
									n=str(i),
									lines='5'
								   )
		if i == 1:
			nh_staffDef.set('dir.dist', '4')
		# Add <clef>
		if args.staff == 's':
			clef = _create_element(uri_mei + 'clef', parent=nh_staffDef, atts=
								   [('shape', 'G'), 
									('line', '2'),
									('dis', '8'), 
									('dis.place', 'below')]
								  )
		else:
			clef = ET.SubElement(nh_staffDef, uri_mei + 'clef', 
								 shape='G' if i==1 else 'F',
								 line='2' if i==1 else '4'
								)
		# Add <keySig>
		keySig = ET.SubElement(nh_staffDef, uri_mei + 'keySig',
							   sig=_get_MEI_keysig(int(args.key)),
							   mode='minor' if args.mode == '1' else 'major'
							  )
		# Add <meterSig> or <mensur>
		if tab_meterSig is not None:
			nh_staffDef.append(tab_meterSig)
		elif tab_mensur is not None:
			# Adapt xml:id and set to nh_mensur
			xml_id = tab_mensur.get(xml_id_key)
			xml_id += '.s1' if i == 1 else '.s2' 
			nh_mensur = copy.deepcopy(tab_mensur)
			nh_mensur.set(xml_id_key, xml_id)
			nh_staffDef.append(nh_mensur)


def _get_MEI_keysig(key: int): # -> str:
	return str(key) + 's' if key > 0 else str(abs(key)) + 'f'


def _handle_section(section: ET.Element, ns: dict, args: argparse.Namespace): # -> None
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
	    </dir>
	    ...
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

	grids_dict = _call_java(['java', '-cp', args.classpath, java_path, args.key, args.mode])
#	grids_dict = _call_java(['java', '-cp', cp, java_path, args.key, args.mode])
	mpcGrid = grids_dict['mpcGrid'] # list
	mpcGridStr = str(mpcGrid)
	altGrid = grids_dict['altGrid'] # list
	altGridStr = str(altGrid)
	pcGrid = grids_dict['pcGrid'] # list
	pcGridStr = str(pcGrid)

	note_ind = 0
	for measure in section.iter(uri_mei + 'measure'):
		accidsInEffect = [[], [], [], [], []]
		other_elements = []
		obsolete_elements = []

		# Get all the direct child elements and iterate over them. These always include <staff> 
		# (as the first element), sometimes followed by others such as <fermata>, <fing>, <annot>) 
		direct_children = measure.findall('*')
		for c in direct_children:
			# Handle <staff>
			if c.tag == uri_mei + 'staff':
				# 1. Tablature <staff>: adapt or remove
				# Adapt
				tab_staff = measure.find('mei:staff', ns)
				tab_staff.set('n', str(int(tab_staff.attrib['n']) + (1 if args.staff == 's' else 2)))
				tab_layer = tab_staff.find('mei:layer', ns)
				# Remove
				if args.tablature == 'n':
					measure.remove(tab_staff)

				# 2. Notehead <staff>(s): create and set as first element(s) in <measure>
				# NB: in the single staff case, nh_staff_2 and its subelements are not used
				nh_staff_1 = ET.Element(uri_mei + 'staff', n='1')
				nh_staff_2 = ET.Element(uri_mei + 'staff', n='2')
				if args.staff == 'd':
					measure.insert(0, nh_staff_2)
				measure.insert(0, nh_staff_1)
				# Add <layer>s
				nh_layer_1 = ET.SubElement(nh_staff_1, uri_mei + 'layer', n='1')
				nh_layer_2 = ET.SubElement(nh_staff_2, uri_mei + 'layer', n='1')
				# Add <rest>s, <chord>s, and <space>s to <layer>s; add corresponding <dir>s after last <staff>
				for tabGrp in tab_layer.iter(uri_mei + 'tabGrp'):
					dur = tabGrp.get('dur')
					dots = tabGrp.get('dots')
					flag = tabGrp.find('mei:tabDurSym', ns)
					rest = tabGrp.find('mei:rest', ns)
					space = tabGrp.find('mei:space', ns)
					# The <tabGrp>'s @xml:id is copied and extended with '.s1' or '.s2', and 
					# - the appropriate variant is used for the corresponding rest/chord/space
					# - the '.s1' variant is used as value for the <dir>'s @startid  
					xml_id_event = tabGrp.get(xml_id_key)

					# Add <rest>s
					if flag != None and (len(tabGrp) == 1 or rest != None or space != None):
						_create_element(uri_mei + 'rest', parent=nh_layer_1, atts=
										[('dur', dur),
										 (xml_id_key, xml_id_event + '.s1')]
									   )
						_create_element(uri_mei + 'rest', parent=nh_layer_2, atts=
										[('dur', dur),
										 (xml_id_key, xml_id_event + '.s2')]
									   )
						# Add <dir>
						_dir = _make_dir(uri_mei, xml_id_event + '.s1', dur, dots)
						measure.insert(len(measure)-1, _dir)	
					# Add <chord>s and <space>s	
					else:
						# If args.staff == 'd', chords are split over the two staffs, where there are
						# three possibilities: 
						# (1) both the upper and the lower staff have a chord;
						# (2) only the upper staff has a chord; 
						# (3) only the lower staff has a chord.
						# In cases (2) and (3), the other staff gets a <space> to fill the gap.
						# <chord>s can therefore not be SubElements, added to the parent <layer>
						# upon creation, but must be Elements appended at the end of this 'else'.
						chord_1 = _create_element(uri_mei + 'chord', atts=
												  [('dur', dur), 
												   ('stem.visible', 'false'),
												   (xml_id_key, xml_id_event + '.s1')]
												 )
						chord_2 = _create_element(uri_mei + 'chord', atts=
												  [('dur', dur), 
												   ('stem.visible', 'false'),
												   (xml_id_key, xml_id_event + '.s2')]
												 )
						# Add <note>s to <chord>
						for element in tabGrp:
							if element != flag:
								try:
									midi_pitch = _get_midi_pitch(int(element.get('tab.course')), 
															 	 int(element.get('tab.fret')), 
															 	 args.tuning)
								except TypeError:
									raise Exception(f"Element {element.tag} with attributes\
													{element.attrib} is either missing tab.course or tab.fret")

								# a. The note is in key and there are no accidentals to correct  
								midi_pitch_class = midi_pitch % 12
								if midi_pitch_class in mpcGrid and not any(accidsInEffect):
									pname = pcGrid[mpcGrid.index(midi_pitch_class)]
									accid = ''
								# b. The note is in key and there are accidentals to correct / the note is not in key
								else:
									cmd = ['java', '-cp', args.classpath, java_path, str(midi_pitch), args.key, 
#									cmd = ['java', '-cp', cp, java_path, str(midi_pitch), args.key, 
						 	 			   mpcGridStr, altGridStr, pcGridStr, str(accidsInEffect)]
									spell_dict = _call_java(cmd)
									pname = spell_dict['pname'] # str
									accid = spell_dict['accid'] # str
									accidsInEffect = spell_dict['accidsInEffect'] # list
								
								nh_note = _create_element(uri_mei + 'note', 
														  parent=chord_1 if args.staff == 's' else\
														         (chord_1 if midi_pitch >= 60 else chord_2), 
														  atts=[('pname', pname),
														        ('oct', str(_get_octave(midi_pitch))),
														   		('head.fill', 'solid'),
														   		(xml_id_key, f'n{note_ind}.{element.get(xml_id_key)}')] +
														   		 ([('accid', accid)] if accid != '' else [])
													 	 )
								note_ind += 1

						# Add <chord> or <space> to <layer>
						if args.staff == 's':
							nh_layer_1.append(chord_1)
						else:
							if len(chord_1) > 0 and len(chord_2) > 0:
								nh_layer_1.append(chord_1)
								nh_layer_2.append(chord_2)						
							else:
								space = _create_element(uri_mei + 'space', atts=
														[('dur', dur),
														 (xml_id_key, xml_id_event + '.s1' if len(chord_1) == 0\
														  else xml_id_event + '.s2')]
													   )
								nh_layer_1.append(chord_1 if len(chord_1) > 0 else space)
								nh_layer_2.append(chord_2 if len(chord_2) > 0 else space)

						# Add <dir>
						_dir = None
						if flag != None:
							_dir = _make_dir(uri_mei, xml_id_event + '.s1', dur, dots)
							measure.insert(len(measure)-1, _dir)

			# Handle other elements
			else:
				# Fermata: needs <dir> (CMN) and <fermata> (= c; tab)
				if c.tag == uri_mei + 'fermata':
					# Make <dir> for CMN
					# NB startid on <fermata> refers to the xml:id of the <tabGrp> the fermata belongs
					# to; the xml:id of the corresponding <chord> or <space> has '.s1' added to that
					xml_id = c.get('startid')[1:] + '.s1'
					_dir = _make_dir(uri_mei, xml_id, 'f', None)
	
					# Add <dir> after the last <dir>, or, if there is none, as the first <dir>
					last_dir_ind = -1
					for i, child in enumerate(measure):
						if child.tag == 'mei:dir':
							last_dir_ind = i
					measure.insert((last_dir_ind+1 if last_dir_ind != -1 else len(measure)-1), _dir)

					# Add to lists	
					if args.tablature == 'y':
						other_elements.append(copy.deepcopy(c))
					obsolete_elements.append(c)
				# Annotation: needs <annot> (CMN) and <annot> (= c; tab) 
				elif c.tag == uri_mei + 'annot':
					# Make <annot> for CMN
					# NB plist on <annot> refers to the xml:id of the tab <note> the annotation belongs 
					# to; the xml:id of the corresponding CMN <note> has 'n<n>.' prepended to that
					xml_id = c.get('plist')[1:]
					annot = copy.deepcopy(c)
					# Find the CMN <note>'s xml:id and the staff it is on
					for i, s in enumerate([nh_staff_1, nh_staff_2]):
						for n in s.findall('.//mei:note', ns):
							curr = n.get(xml_id_key)
							# NB The part after the 'and' ensures that the <note> is the CMN <note>  
							if curr.endswith(xml_id) and (len(curr) > len(xml_id)):
								annot.set('plist', '#' + curr)
								annot.set(xml_id_key, f'{annot.get(xml_id_key)}.s{i+1}')
								break
						# If <note> was found in <staff> 1 
						if annot.get('plist').endswith('.s1'):
							break

					# Add to lists
					other_elements.append(annot)
					if args.tablature == 'y':
						other_elements.append(copy.deepcopy(c))
					obsolete_elements.append(c)
				# Fingering: needs <fing> (= c; tab)
				elif c.tag == uri_mei + 'fing':
					# Add to lists
					if args.tablature == 'y':
						other_elements.append(copy.deepcopy(c))
					obsolete_elements.append(c)

		# Add other elements to <measure> in fixed sequence
		fermatas = [e for e in other_elements if e.tag == uri_mei + 'fermata']
		annots = [e for e in other_elements if e.tag == uri_mei + 'annot']
		fings = [e for e in other_elements if e.tag == uri_mei + 'fing']
		for e in fermatas + annots + fings:
			measure.append(e)

		# Remove obsolete elements
		for obsolete in obsolete_elements:
			measure.remove(obsolete)

		if verbose:
			for elem in measure:
				print(elem.tag, elem.attrib)
				for e in elem:
					print(e.tag, e.attrib)
					for ee in e:
						print(ee.tag, ee.attrib)
						for eee in ee:
							print(eee.tag, eee.attrib)


# NB For debugging: set, where this function is called, use_Popen=True
def _call_java(cmd: list, use_Popen: bool=False): # -> dict:
	# For debugging
	if use_Popen:
		process = Popen(cmd, stdout=PIPE, stderr=PIPE, shell=False)
		output, errors = process.communicate()
		outp = output.decode('utf-8') # str
		print(errors)
		print(outp)
	# For normal use
	else:
		process = run(cmd, capture_output=True, shell=False)
		outp = process.stdout # bytes
#	print(outp)
 
	return json.loads(outp)


def _make_dir(uri_mei: str, xml_id: str, dur: int, dots: int): # -> 'ET.Element'
	d = ET.Element(uri_mei + 'dir',
				   place='above', 
				   startid='#' + xml_id
				  )
	
	# Non-fermata case
	if dur != 'f':
		_create_element(uri_mei + 'symbol', parent=d, atts=
						[('glyph.auth', 'smufl'), 
						 ('glyph.name', smufl_lute_durs[int(dur)])]
				   	   )
		if dots != None:
			_create_element(uri_mei + 'symbol', parent=d, atts=
							[('glyph.auth', 'smufl'), 
							 ('glyph.name', smufl_lute_durs['.'])]
						   )
	# Fermata case 
	else:
		_create_element(uri_mei + 'symbol', parent=d, atts=
						[('glyph.auth', 'smufl'), 
						 ('glyph.name', smufl_lute_durs['f'])]
				   	   )

	return d


def _get_midi_pitch(course: int, fret: int, tuning: str): # -> int:
	# Determine the MIDI pitches for the open courses
	abzug = 0 if not '-' in tuning else 2
	open_courses = [67, 62, 57, 53, 48, (43 - abzug)]
	if tuning[0] != 'G':
		shift_interv = shift_intervals[tuning[0]]
		open_courses = list(map(lambda x: x+shift_interv, open_courses))
	return open_courses[course-1] + fret


def _get_octave(midi_pitch: int): # -> int:
	c = midi_pitch - (midi_pitch % 12)
	return int((c / 12) - 1)


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


def transcribe(infiles: list, arg_paths: dict, args: argparse.Namespace): # -> None
	inpath = arg_paths['inpath']
	outpath = arg_paths['outpath']
	
	for infile in infiles:
		filename, ext = os.path.splitext(os.path.basename(infile)) # input file name, extension
		outfile = filename + '-dipl' + ext # output file

		xml_file = os.path.join(inpath, infile)

		# Manually extract processing instructions (PIs): <?xml> declaration and <?xml-model> PI 
		with open(xml_file, 'r', encoding='utf-8') as file:
			content = file.read()
			lines = content.split('\n')
			declaration = lines[0] + '\n'
			if lines[1][1:].startswith('?xml-model'):
				model_pi = lines[1] + '\n'
			else:
				model_pi = ''

		# Handle namespaces
		ns = _handle_namespaces(xml_file)
		uri = '{' + ns['mei'] + '}'

		# Get the main MEI elements
		tree, meiHead, music = _parse_tree(xml_file, ns)

		# Handle <scoreDef>
		score = music.findall('.//' + uri + 'score')[0]
		scoreDef = score.find('mei:scoreDef', ns)
		_handle_scoreDef(scoreDef, ns, args)

		# Handle <section>
		section = score.find('mei:section', ns)
		_handle_section(section, ns, args)

		# Fix indentation
		ET.indent(tree, space='\t', level=0)

#		# Write to file
#		tree.write(os.path.join(outpath, outfile))

		# Prepend declaration and processing instructions
		xml_str = ET.tostring(tree.getroot(), encoding='unicode')
		xml_str = f'{declaration}{model_pi}{xml_str}'
		with open(os.path.join(outpath, outfile), 'w', encoding='utf-8') as file:
			file.write(xml_str)
