import argparse
import copy
import json
import os
import sys
from lxml import etree
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
from py.lxml_tools import (get_namespaces, collect_xml_ids, get_wrapper_elem, unwrap,
						   make_element)
from py.mei_tools import (get_main_mei_elements, get_tuning, remove_empty_markup,  
					  	  get_mei_keysig, get_octave, get_midi_pitch, TUNINGS)
from py.tools import add_unique_id, get_isodate

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
TOOL_NAME = 'abtab -- transcriber'


# Helper functions (called once or more by main functions or other helper functions) -->
def call_java(cmd: list, use_Popen: bool=False) -> dict:
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
		print('cmd:   ', cmd[3], '--', cmd[5])
		print('errors:', errors)
		print('output:', outp)
	# For normal use
	else:
		process = run(cmd, capture_output=True, shell=False)
		outp = process.stdout.decode('utf-8') # str
#		outp = process.stdout # bytes
#		print(outp)

	return json.loads(outp)


# Main functions (called once by principal code) -->
def handle_encodingDesc(encodingDesc: etree._Element, ns: dict, args: argparse.Namespace) -> None:
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

	# Make new <application>
	application = make_element(f'{URI_MEI}application', 
						 	   atts=[(XML_ID_KEY, add_unique_id('a', XML_IDS)[-1]),
							   		 ('isodate', get_isodate()), 
							   		 ('version', args.version)]
							  )
	etree.SubElement(application, f'{URI_MEI}name', 
				  **{f'{XML_ID_KEY}': add_unique_id('n', XML_IDS)[-1]}
				 ).text = TOOL_NAME
	etree.SubElement(application, f'{URI_MEI}p', 
				  **{f'{XML_ID_KEY}': add_unique_id('p', XML_IDS)[-1]}
				 ).text = f'Input file: {args.file}'
	etree.SubElement(application, f'{URI_MEI}p', 
				  **{f'{XML_ID_KEY}': add_unique_id('p', XML_IDS)[-1]}
				 ).text = f'Output file: {os.path.splitext(args.file)[0]}-dipl{MEI}'
	
	# Get or create <appInfo>
	appInfo = encodingDesc.find('.//mei:appInfo', ns)
	if appInfo is None:
		appInfo = etree.SubElement(encodingDesc, f'{URI_MEI}appInfo',
								**{f'{XML_ID_KEY}': add_unique_id('ai', XML_IDS)[-1]}
				 			   )
#	# Else: remove any existing abtab -- transcriber <application>s
#	else:
#		if overwrite:
#			for a in appInfo.findall('.//mei:application', ns):
#				name = a.find('.//mei:name', ns)
#				if name is not None and name.text and name.text == TOOL_NAME:
#					appInfo.remove(a)
	
	# Add <application> 			
	appInfo.append(application)


def handle_scoreDef(scoreDef: etree._Element, ns: dict, args: argparse.Namespace) -> None:
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
				course = etree.SubElement(tab_tuning, f'{URI_MEI}course',
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
	nh_staffGrp = etree.Element(f'{URI_MEI}staffGrp', 
							 **{f'{XML_ID_KEY}': add_unique_id('sg', XML_IDS)[-1]})
	if args.score == DOUBLE:
		nh_staffGrp.set('symbol', 'bracket')
		nh_staffGrp.set('bar.thru', 'true')
	staffGrp.insert(0, nh_staffGrp)
	# Add <staffDef>(s)
	for i in [1] if args.score == SINGLE else [1, 2]:
		nh_staffDef = etree.SubElement(nh_staffGrp, f'{URI_MEI}staffDef',
									**{f'{XML_ID_KEY}': add_unique_id('sd', XML_IDS)[-1]},
									n=str(i),
									lines='5',
									notationtype='tab.staff-like'
								   )
		if i == 1:
			nh_staffDef.set('dir.dist', '4') # TODO still needed without <dir>s?
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
				clef = etree.SubElement(nh_staffDef, f'{URI_MEI}clef', 
									 **{f'{XML_ID_KEY}': add_unique_id('c', XML_IDS)[-1]},
									 shape='G' if i==1 else 'F',
									 line='2' if i==1 else '4'
									)
		# Add <keySig>
		# <keySig> is only used in first staffDef, not in those for any subsequent <section>s
		# NB Theoretically, the <section> could be in a different key -- but currently a single key 
		#    is assumed for the whole piece
		if is_first_scoreDef:
			keySig = etree.SubElement(nh_staffDef, f'{URI_MEI}keySig',
								   **{f'{XML_ID_KEY}': add_unique_id('ks', XML_IDS)[-1]},
								   sig=get_mei_keysig(KEY),
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


def handle_section(section: etree._Element, ns: dict, args: argparse.Namespace) -> tuple:
	"""
	Basic structure of <section>:

	<section>
	  <measure>
	    <staff n='1'>
	      <layer>
	        <tabGrp>
	          (<tabDurSym ... />)
	          (<note ... />)
	          (<rest ... />)
	        </tabGrp>
	      </layer>
	    </staff>
		(<staff n='2' ... />)
		(<staff n='3' ... />)
	    (<dir>)
	    (<fing>)
	    (<fermata>)
	  </measure>
	  ...
	</section>
	"""

	notes_unspelled_by_ID = {}
	regular_elements = [f'{URI_MEI}{e}' for e in ['beam', 'tabGrp', 'tabDurSym', 'note', 'rest']]
	markup_elements = ([f'{URI_MEI}{e}' for e in ['abbr', 'add', 'choice', 'corr', 'cpMark', 'damage', 'del', 'expan',
												  'metaMark', 'orig', 'reg', 'restore', 'sic', 'subst', 'supplied', 'unclear']])
	performance_related_att_types = ['hold', 'split_course']
	other_att_types = ['ref', 'rpt', 'finis']

	for measure in section.iter(f'{URI_MEI}measure'):
		# Mapping of xml:ids in staff: key = nh_staff_<n> xml:id; val = tab_staff xml:id    
		xml_id_mapping = {}

		# 1. Handle tablature <staff>
		tab_staff = measure.find('mei:staff', ns)
		# Adapt
		tab_staff_num = 1 if args.placement == TOP else (2 if args.score == SINGLE else 3)
		tab_staff.set('n', str(tab_staff_num))
		# Remove
		if args.tablature == NO:
			measure.remove(tab_staff)

		# 2. Handle notehead <staff>(s)
		# Make copies of tab_staff; keep xml:ids so they can be used for reference  
		nh_staff_1 = copy.deepcopy(tab_staff)
		nh_staff_1_num = 1 if args.placement == BOTTOM else 2
		nh_staff_1.set('n', str(nh_staff_1_num))
		# Build index of elements by xml:id
		id_index_nh_staff_1 = {elem.get(XML_ID_KEY): elem for elem in nh_staff_1.iter() if elem.get(XML_ID_KEY)}
		if args.score == DOUBLE:
			nh_staff_2 = copy.deepcopy(tab_staff)
			nh_staff_2_num = nh_staff_1_num + 1
			nh_staff_2.set('n', str(nh_staff_2_num))
			# Build index of elements by xml:id
			id_index_nh_staff_2 = {elem.get(XML_ID_KEY): elem for elem in nh_staff_2.iter() if elem.get(XML_ID_KEY)}

		# First pass: iterate over tab_staff; modify elements in nh_staff_1 and _2. 
		# Handled elements are <beam>, <tabGrp>, <tabDurSym>, <note>, <rest>. 
		# xml:ids for <tabGrp> and <note> must be made already in the first pass
		#
		# editorial contains all of <tab_staff>'s' markup elements with a direct
		# child that may be removed when args.score == DOUBLE (i.e., a <note> or
		# <tabDurSym>), possibly leaving the editorial element empty
		editorial = []
		for elem in list(tab_staff.iter()): # list() makes it safe to modify (replace/remove) during iteration
			# Skip comments
			if isinstance(elem, etree._Comment):
				continue

			name = etree.QName(elem).localname
			xml_id = elem.get(XML_ID_KEY)

			# Check if elem is a markup element with a <note> or <tabDurSym> as direct child 
			if elem.tag in markup_elements:
				for child in elem:
					if child.tag == f'{URI_MEI}note' or child.tag == f'{URI_MEI}tabDurSym':
						editorial.append(xml_id)

			# a. Handle <beam>: remove (if args.score == DOUBLE)
			if elem.tag == f'{URI_MEI}beam':
				if args.score == DOUBLE:
					unwrap(id_index_nh_staff_2[xml_id])

			# b. Handle <tabGrp>: set new xml:id(s) (needed for cross-linking)
			# and add to mapping; cross-link (if args.score == DOUBLE)  
			elif elem.tag == f'{URI_MEI}tabGrp':
				nh_tg_1 = id_index_nh_staff_1[xml_id]
				nh_xml_id_1 = add_unique_id(name[0], XML_IDS)[-1]
				nh_tg_1.set(XML_ID_KEY, nh_xml_id_1)
				xml_id_mapping[nh_xml_id_1] = xml_id
				if args.score == DOUBLE:
					nh_tg_2 = id_index_nh_staff_2[xml_id]
					nh_xml_id_2 = add_unique_id(name[0], XML_IDS)[-1]
					nh_tg_2.set(XML_ID_KEY, nh_xml_id_2)
					xml_id_mapping[nh_xml_id_2] = xml_id
					nh_tg_1.set('corresp', '#' + nh_xml_id_2)
					nh_tg_2.set('corresp', '#' + nh_xml_id_1)

				# NB Types of rest are
				# 1.    <tabGrp> containing <tabDurSym> (above or inside the tablature staff)
				# 2. a. <tabGrp> containing <tabDurSym> + <rest> (rhythm-flag-looking)
				#    b. <tabGrp> containing <tabDurSym> + <rest> (rest-looking)
				# 3. a. <tabGrp> containing <rest> (rhythm-flag-looking)
				#    b. <tabGrp> containing <rest> (rest-looking)
				if elem.find(f'.//{URI_MEI}note') is None:
					tds = elem.find(f'.//{URI_MEI}tabDurSym')
					rest = elem.find(f'.//{URI_MEI}rest')
					rest_case_1 = tds is not None and rest is None
					rest_case_2a = tds is not None and rest is not None and rest.get('glyph.name') in SMUFL_LUTE_DURS.values() # use @type
					rest_case_2b = tds is not None and rest is not None and rest.get('glyph.name') not in SMUFL_LUTE_DURS.values() # use @type
					rest_case_3a = tds is None and rest is not None and rest.get('glyph.name') in SMUFL_LUTE_DURS.values() # use @type
					rest_case_3b = tds is None and rest is not None and rest.get('glyph.name') not in SMUFL_LUTE_DURS.values() # use @type

			# c. Handle <tabDurSym>: remove @tab.line; remove (if args.score == DOUBLE) 
			elif elem.tag == f'{URI_MEI}tabDurSym':
				nh_tds_1 = id_index_nh_staff_1[xml_id]
				if 'tab.line' in elem.attrib:		
					nh_tds_1.attrib.pop('tab.line', None)
				if args.score == DOUBLE:
					nh_tds_2 = id_index_nh_staff_2[xml_id]
					nh_tds_2.getparent().remove(nh_tds_2)

			# d. Handle <note>: make notehead <note>; set new xml:id (needed for notes_unspelled_by_ID)
			# and add to mapping; replace with notehead <note>/remove tab <note>
			elif elem.tag == f'{URI_MEI}note':
				nh_xml_id = add_unique_id(name[0], XML_IDS)[-1]
				course = elem.get('tab.course')
				fret = elem.get('tab.fret')
				midi_pitch = (None if (course is None or fret is None) else	
							  get_midi_pitch(int(course), int(fret), TUNING))
				nh_note = make_element(f'{URI_MEI}note', 
									   atts=[(XML_ID_KEY, nh_xml_id)] +
									   ([('pname', ''), ('oct', str(get_octave(midi_pitch)))] if midi_pitch 
									   else [('visible', 'false')])
									  )

				n_1 = id_index_nh_staff_1[xml_id]
				if args.score == SINGLE:
					n_1.getparent().replace(n_1, nh_note)
				else:
					n_2 = id_index_nh_staff_2[xml_id]
					if midi_pitch >= 60:
						n_1.getparent().replace(n_1, nh_note) 
						n_2.getparent().remove(n_2)
					else:
						n_2.getparent().replace(n_2, nh_note)
						n_1.getparent().remove(n_1)

				xml_id_mapping[nh_xml_id] = xml_id 
				notes_unspelled_by_ID[nh_xml_id] = (measure.get('n'), midi_pitch)

			# e. Handle <rest>: remove @tab.line
			elif elem.tag == f'{URI_MEI}rest':
				nh_r_1 = id_index_nh_staff_1[xml_id]
				if 'tab.line' in elem.attrib:		
					nh_r_1.attrib.pop('tab.line', None)
				if args.score == DOUBLE:
					nh_r_2 = id_index_nh_staff_2[xml_id]
					if 'tab.line' in elem.attrib:
						nh_r_2.attrib.pop('tab.line', None)

		# Second pass: remove all editorial elements now empty due to removal 
		# of <note> or <tabDurSym>
		remove_empty_markup(editorial, markup_elements, id_index_nh_staff_1)
		if args.score == DOUBLE:
			remove_empty_markup(editorial, markup_elements, id_index_nh_staff_2)

		# Third pass: iterate over nh_staff_1 and _2; update remaining xml:ids and add to mapping
		for i, staff in enumerate([nh_staff_1] if args.score == SINGLE else [nh_staff_1, nh_staff_2]):
			for elem in list(staff.iter()):
				# Skip comments
				if isinstance(elem, etree._Comment):
					continue

				xml_id = elem.get(XML_ID_KEY)
				# If xml_id is in xml_id_mapping, elem's xml:id has been created and added  
				# to xml_id_mapping in the first pass. If not, thus must still be done
				if xml_id not in xml_id_mapping:	
					name = etree.QName(elem).localname
					nh_xml_id = add_unique_id(name[0], XML_IDS)[-1]
					elem.set(XML_ID_KEY, nh_xml_id)
					xml_id_mapping[nh_xml_id] = xml_id

		# Insert staves in <measure>
		measure.insert(nh_staff_1_num - 1, nh_staff_1)
		if args.score == DOUBLE:
			measure.insert(nh_staff_2_num - 1, nh_staff_2)			

		# 3. Handle optional sibling elements of <staff> 
		# a. <dir>: performance-related <dir>s are only shown in the tab staff; 
		# non-performance-related <dir>s are shown in both staffs 
		for elem in measure.findall('.//mei:dir', ns):
			# Adapt
			elem.set('staff', str(tab_staff_num))
			elem_wrapped = get_wrapper_elem(elem, measure)
			# Duplicate and insert in <measure> (if not performance_related_att_types)
			if elem.get('type') not in performance_related_att_types:
				att_list = [('staff', str(nh_staff_1_num))]
				if elem.get('type') == 'finis' and args.score == DOUBLE:
					att_list.append(('vo', '-10vu'))
				nh_d_wrapped = _duplicate_for_nh_staff(elem_wrapped, 'dir', att_list, ns)
				elem_wrapped.addprevious(nh_d_wrapped)
			# Remove
			if args.tablature == NO:
				measure.remove(elem_wrapped)

		# b. <fermata>
		for elem in measure.findall('.//mei:fermata', ns):
			elem_wrapped = get_wrapper_elem(elem, measure)
			# Duplicate and insert in <measure>
			# Get xml:id of tabGrp in nh_staff_1 to use as @startid value
			nh_tg_xml_id = next(k for k, v in xml_id_mapping.items() if v == elem.get('startid').lstrip('#'))
			att_list = [('startid', '#' + nh_tg_xml_id)]
			nh_f_wrapped = _duplicate_for_nh_staff(elem_wrapped, 'fermata', att_list, ns) 
			elem_wrapped.addprevious(nh_f_wrapped)
			# Remove
			if args.tablature == NO:
				measure.remove(elem_wrapped)

		# c. <fing>				
		for elem in measure.findall('.//mei:fing', ns):
			elem_wrapped = get_wrapper_elem(elem, measure)
			# Remove
			if args.tablature == NO:
				measure.remove(elem_wrapped)

		if VERBOSE:
			for elem in measure:
				print(elem.tag, elem.attrib)
				for e in elem:
					print(e.tag, e.attrib)
					for ee in e:
						print(ee.tag, ee.attrib)
						for eee in ee:
							print(eee.tag, eee.attrib)

	# Convert notes_unspelled_by_ID to a list
	notes_unspelled_by_ID = [(xml_id, meas, midip) for xml_id, (meas, midip) in notes_unspelled_by_ID.items()]

	return (section, notes_unspelled_by_ID)


def _duplicate_for_nh_staff(te_wrapped: etree._Element, name: str, att_list: list[tuple], ns: dict) -> etree._Element:
	"""
	Duplicates a (possibly wrapped) tablature staff element of the given name for the notehead staff.

	Args:
		te_wrapped: The tablature staff element to duplicate (either the target element
					itself or a wrapper containing it).
		name: 		The name of the target element.
		att_list: 	List of (attribute, value) tuples to set on the target element.
		ns: 		Namespace dictionary for XPath lookups.

	Returns:
		The duplicated (possibly wrapped) notehead staff element, with updated xml:ids 
		and attributes applied.
	"""
	nhe_wrapped = copy.deepcopy(te_wrapped) # nhe = notehead staff elem; te = tab staff elem
	# Update xml:ids
	_update_xml_ids(nhe_wrapped)
	# Set attributes 
	# xpath() finds any <name> descendant or the element itself if it is a <name>
	nhe = nhe_wrapped.xpath(f'.//mei:{name} | self::mei:{name}', namespaces=ns)[0]
	for (att, val) in att_list:
		nhe.set(att, val)

	return nhe_wrapped


def _update_xml_ids(elem: etree._Element) -> etree._Element:
	for e in list(elem.iter()):
		# Skip comments
		if isinstance(e, etree._Comment):
			continue

		name = etree.QName(e).localname
		e.set(XML_ID_KEY, add_unique_id(name[0], XML_IDS)[-1])

	return elem


def spell_pitch(section: etree._Element, notes_unspelled_by_ID: list, args: argparse.Namespace) -> None:
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
def transcribe(in_path: str, out_path: str, args: argparse.Namespace) -> None:
	# 0. File processing
	in_file = args.file
	filename, ext = os.path.splitext(in_file) # in_file is already basename (see method call in transcriber.py)
	out_file = filename + '-dipl-new' + MEI
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

	# 1. Preliminaries
	# a. Get root (<mei>) and tree
	root = etree.fromstring(mei_str.encode('utf-8'))
	tree = etree.ElementTree(root)	
	# b. Get namespaces and URIs
	ns = get_namespaces(root, 'mei')
	global URI_MEI
	URI_MEI = f'{{{ns['mei']}}}'
	global URI_XML
	URI_XML = f'{{{ns['xml']}}}'
	global XML_ID_KEY
	XML_ID_KEY = f'{URI_XML}id'
	# c. Get main MEI elements (<meiHead>, <music>), and <score>
	meiHead, music = get_main_mei_elements(root, ns)
	score = music.find('.//mei:score', ns)
	# d. Collect all xml:ids; map the original xml:ids
	global XML_IDS
	XML_IDS = collect_xml_ids(root, ns)
	global ORIG_XML_IDS # TODO keep?
	ORIG_XML_IDS = {
		elem.attrib[XML_ID_KEY]: elem for elem in root.iter() if XML_ID_KEY in elem.attrib
	}

	# 2. Handle <encodingDesc>
	encodingDesc = meiHead.find('.//mei:encodingDesc', ns)
	handle_encodingDesc(encodingDesc, ns, args)

	# 3. Handle <scoreDef>s
	scoreDefs = score.findall('.//mei:scoreDef', ns)
	for scoreDef in scoreDefs:
		handle_scoreDef(scoreDef, ns, args)

	# 4. Handle <section>s
	sections = score.findall('mei:section', ns)
	for section in sections:
		section, notes_unspelled_by_ID = handle_section(section, ns, args)
		spell_pitch(section, notes_unspelled_by_ID, args)

	# 5. Fix indentation
	etree.indent(tree, space='\t')

	# 6. Add processing instructions (<?xml> declaration and <?xml-model>  
	# processing instructions), which are not included in root 
	lines = mei_str.split('\n')
	declaration = lines[0] + '\n'
	model_pi = ''
	for line in lines:
		if line[1:].startswith('?xml-model'):
			model_pi += line + '\n'
	xml_str = etree.tostring(root, encoding='unicode')
	xml_str = f'{declaration}{model_pi}{xml_str}'

	# 7. Write to file
	with open(os.path.join(out_path, out_file), 'w', encoding='utf-8') as file:
		file.write(xml_str)
