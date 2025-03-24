"""
This script must be called from the folder that holds it, and that furthermore 
contains the following subfolders:
- in/	contains the input MEI file
- out/	where the output MEI file is stored
- java/	contains the Java code required for the pitch spelling:
        - utils/lib/commons-lang3-3.8.1.jar
        - utils/bin/tools/music/PitchKeyTools.class 
        - utils/bin/tools/text/StringTools.class

NB: Updated from Python 3.6.0 to 3.12.0 for this script.

Relevant Python documentation
- https://docs.python.org/3/library/argparse.html

TODO
- have the choices rendered automatically in the parser.add:argument()s' help='...' 
  (or remove metavar='')
- how do I make a rest invisible?
- diplomat.py
  - @head.fill on <note> is not rendered in Verovio
  - show flags option: do not show flags above notehead notation (/tab) if tab + nh

"""

import argparse
import glob
import json
import os
import re
import sys
from diplomat import transcribe
from parser_vals import *


parser = argparse.ArgumentParser(prog=		 'diplomat',
								 description='Creates a diplomatic transcription in notehead notation.',
								 epilog=	 'Stores a new MEI file in the output folder (\'out/\').')
# Optional args
parser.add_argument('-u', '--tuning', 
					choices=[F, F6Eb, G, G6F, A, A6G, INPUT], 
					default=INPUT,
					metavar='', 
					help=f'the tuning; options are [{F}, {F6Eb}, {G}, {G6F}, {A}, {A6G}], default is {G}')
parser.add_argument('-k', '--key', 
					choices=[str(i) for i in list(range(-5, 6, 1))], 
					default=INPUT, 
					metavar='',
					help='the key signature for the transcription, expressed as its\
						  number of accidentals (where a negative number indicates flats);\
						  options are [-5, ..., 5], default is 0')
parser.add_argument('-m', '--mode', 
					choices=[MAJOR, MINOR], 
					default=MAJOR,
					metavar='', 
					help='the key signature\'s \'mode\': major (0) or minor (1);\
						  options are [0, 1], default is 0')
parser.add_argument('-s', '--staff', 
					choices=[SINGLE, DOUBLE], 
					default=DOUBLE,
					metavar='', 
					help='the staff type: single or double;\
						  options are [s, d], default is d')
parser.add_argument('-t', '--tablature', 
					choices=[YES, NO], 
					default=YES,
					metavar='',
					help='whether or not to retain the tab in the transcription;\
						  options are [y, n], default is y')
parser.add_argument('-y', '--type', 
					choices=[FLT, ILT, SLT, GLT, INPUT], 
					default=INPUT,
					metavar='',
					help='the tablature type;\
						  options are [FLT, ILT, SLT, GLT], default is FLT')
parser.add_argument('-f', '--file', 
					help='the input file')
# Positional args
parser.add_argument('dev', 
					help='true if model development case')
parser.add_argument('rootpath', 
					help='the abtab home directory.')
parser.add_argument('libpath', 
					help='the directory holding the code.')
parser.add_argument('classpath', 
					help='the Java classpath')

args = parser.parse_args()

if __name__ == "__main__":
#	scriptpath = os.getcwd() # full path to script

	# Paths
	root_path = args.rootpath
	lib_path = args.libpath
	paths_file = 'paths-dev.json' if args.dev == 'true' else 'paths.json'
	with open(os.path.join(lib_path, paths_file), 'r') as file:
		json_str = file.read()
	json_str = re.sub(r'//.*', '', json_str) # remove '//' comments
	paths_json = json.loads(json_str)
	dipl_path = os.path.join(root_path, paths_json['paths']['DIPLOMAT_PATH'])
	in_path = os.path.join(dipl_path, 'in') # full path to input file
	out_path = os.path.join(dipl_path, 'out') # full path to output file

	# List files
	infiles = []
	# Selected file
	if args.file is not None:
		infile = os.path.split(args.file)[-1] # input file
		infiles.append(infile)
	# All files in in_path folder
	else:
		for ext in ALLOWED_FILE_FORMATS:
			pattern = os.path.join(in_path, f'*{ext}')
			infiles.extend(glob.glob(pattern))
		infiles = [os.path.basename(f) for f in infiles]

	paths = {'inpath': in_path, 'outpath': out_path}
	for infile in infiles:
		transcribe(infile, paths, args)
