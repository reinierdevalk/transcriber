# TODO
# - have the choices rendered automatically in the parser.add:argument()s' help='...' 
#   (or remove metavar='')
# - how do I make a rest invisible?
# - diplomat.py
#   - @head.fill on <note> is not rendered in Verovio
#   - show flags option: do not show flags above notehead notation (/tab) if tab + nh

import argparse
import glob
import json
import os
import re
import sys

# Ensure that Python can find .py files in utils/py/ regardless of where the script
# is run from by adding the path holding the code (<lib_path>) to sys.path
# __file__ 					= <lib_path>/transcriber/py/transcriber.py
# os.path.dirname(__file__) = <lib_path>/transcriber/py/
# '../../' 					= up two levels, i.e., <lib_path>
lib_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../utils'))
if lib_path not in sys.path:
	sys.path.insert(0, lib_path)

from diplomat import transcribe
from py.constants import *


# Main functions -->
def parse_args(): # -> None:
	"""
	See https://docs.python.org/3/library/argparse.html
	"""

	parser = argparse.ArgumentParser(prog=		 'diplomat',
									 description='Creates a diplomatic transcription in notehead notation.',
									 epilog=	 'Stores a new MEI file in the output folder (\'out/\').')
	# Optional args
	parser.add_argument('-k', '--key', 
						choices=[str(i) for i in list(range(-5, 6, 1))], 
						default=INPUT, 
						metavar='',
						help=''
					   )
	parser.add_argument('-x', '--accidentals', 
						choices=[YES, NO], 
						default=NO, 
						metavar='',
						help=''
					   )
	parser.add_argument('-m', '--mode', 
						choices=[MAJOR, MINOR], 
						default=MAJOR,
						metavar='', 
						help=''
					   )
	parser.add_argument('-u', '--tuning', 
						choices=[F, F6Eb, G, G6F, A, A6G, INPUT], 
						default=INPUT,
						metavar='', 
						help=''
					   )
	parser.add_argument('-s', '--score', 
						choices=[SINGLE, DOUBLE, VOCAL], 
						default=DOUBLE,
						metavar='', 
						help=''
					   )
	parser.add_argument('-t', '--tablature', 
						choices=[YES, NO], 
						default=YES,
						metavar='',
						help=''
					   )
	parser.add_argument('-y', '--type', 
						choices=[FLT, ILT, SLT, GLT, INPUT], 
						default=INPUT,
						metavar='',
						help=''
					   )
	parser.add_argument('-p', '--placement', 
						choices=[TOP, BOTTOM], 
						default=BOTTOM,
						metavar='',
						help=''
					   )
	parser.add_argument('-c', '--custom', 
						choices=['dlaute', 'plaute', 'user'], 
						metavar='',
						help=''
					   )	
	parser.add_argument('-f', '--file', help='')
#	parser.add_argument('-h', '--help', help='')
	# Positional args
	parser.add_argument('dev', help='')
	parser.add_argument('rootpath', help='')
	parser.add_argument('libpath', help='')
	parser.add_argument('classpath', help='')

	return parser.parse_args()


# Principal code -->
if __name__ == "__main__":
#	scriptpath = os.getcwd() # full path to script
	args = parse_args()

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
	in_files = []
	# Selected file
	if args.file is not None:
		in_file = os.path.split(args.file)[-1] # input file
		in_files.append(in_file)
	# All files in in_path folder
	else:
		for ext in ALLOWED_FILE_FORMATS:
			pattern = os.path.join(in_path, f'*{ext}')
			in_files.extend(glob.glob(pattern))
		in_files = [os.path.basename(f) for f in in_files]

	for in_file in in_files:
		transcribe(in_file, in_path, out_path, args)
