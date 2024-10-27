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

parser = argparse.ArgumentParser(prog=		 'diplomat',
								 description='Creates a diplomatic transcription in notehead notation.',
								 epilog=	 'Stores a new MEI file in the output folder (\'out/\').')
# Optional args
parser.add_argument('-u', '--tuning', 
					choices=['F', 'F-', 'G', 'G-', 'A', 'A-'], 
					default='G',
					metavar='', 
					help='the tuning; options are [F, F-, G, G-, A, A-], default is G')
parser.add_argument('-k', '--key', 
					choices=[str(i) for i in list(range(-5, 6, 1))], 
					default='0', 
					metavar='',
					help='the key signature for the transcription, expressed as its\
						  number of accidentals (where a negative number indicates flats);\
						  options are [-5, ..., 5], default is 0')
parser.add_argument('-m', '--mode', 
					choices=['0', '1'], 
					default='0',
					metavar='', 
					help='the key signature\'s \'mode\': major (0) or minor (1);\
						  options are [0, 1], default is 0')
parser.add_argument('-s', '--staff', 
					choices=['s', 'd'], 
					default='s',
					metavar='', 
					help='the staff type: single or double;\
						  options are [s, d], default is s')
parser.add_argument('-t', '--tablature', 
					choices=['y', 'n'], 
					default='y',
					metavar='',
					help='whether or not to retain the tab in the transcription;\
						  options are [y, n], default is y')
parser.add_argument('-y', '--type', 
					choices=['FLT', 'ILT', 'SLT', 'GLT'], 
					default='FLT',
					metavar='',
					help='the tablature type;\
						  options are [FLT, ILT, SLT, GLT], default is FLT')
parser.add_argument('-f', '--file', 
					help='the input file')
#					help='the input file; can be preceded by the name of the input folder (\'in/\')')
# Positional args
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
	with open(os.path.join(lib_path, 'paths.json'), 'r') as file:
		json_str = file.read()
	json_str = re.sub(r'//.*', '', json_str) # remove '//' comments
	paths_json = json.loads(json_str)
	dipl_path = os.path.join(root_path, paths_json['DIPLOMAT_PATH'])
	in_path = os.path.join(dipl_path, 'in') # full path to input file
	out_path = os.path.join(dipl_path, 'out') # full path to output file
	# TODO can go; covered by install.sh
	if not os.path.exists(out_path):
		os.makedirs(out_path)

	# List files
	infiles = []
	# Selected file
	if args.file is not None:
		infile = os.path.split(args.file)[-1] # input file
		infiles.append(infile)
	# All files in in_path folder
	else:
		for ext in ['.mei', '.xml']:
			pattern = os.path.join(in_path, f'*{ext}')
			infiles.extend(glob.glob(pattern))
		infiles = [os.path.basename(f) for f in infiles]

#	print("FILES", infiles)
#	print(scriptpath)
#	print("ROOT", args.rootpath)
#	print("LIB", args.libpath)
#	print(args.classpath)
#	print("DIPL", dipl_path)
#	paths = {
#			 'inpath': os.path.join(scriptpath, 'in'), # full path to input file
#			 'outpath': os.path.join(scriptpath, 'out') # full path to output file
#			}

	paths = {'inpath': in_path, 'outpath': out_path}
	transcribe(infiles, paths, args)
