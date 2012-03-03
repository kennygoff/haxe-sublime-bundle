#fix for ubuntu
import sys
sys.path.append("/usr/lib/python2.6/")
sys.path.append("/usr/lib/python2.6/lib-dynload")

import sublime, sublime_plugin
import subprocess
import tempfile
import os
import xml.parsers.expat
import re
import codecs
import glob
import hashlib
import shutil
from xml.etree import ElementTree
from subprocess import Popen, PIPE

try:
    STARTUP_INFO = subprocess.STARTUPINFO()
    STARTUP_INFO.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    STARTUP_INFO.wShowWindow = subprocess.SW_HIDE
except (AttributeError):
	STARTUP_INFO = None

def runcmd( args, input=None ):
	try:
		p = Popen(args, stdout=PIPE, stderr=PIPE, stdin=PIPE, startupinfo=STARTUP_INFO)
		if isinstance(input, unicode):
			input = input.encode('utf-8')
		out, err = p.communicate(input=input)
		return (out.decode('utf-8') if out else '', err.decode('utf-8') if err else '')
	except (OSError, ValueError) as e:
		err = u'Error while running %s: %s' % (args[0], e)
		return ("", err)

compilerOutput = re.compile("^([^:]+):([0-9]+): characters? ([0-9]+)-?([0-9]+)? : (.*)", re.M)
compactFunc = re.compile("\(.*\)")
compactProp = re.compile(":.*\.([a-z_0-9]+)", re.I)
spaceChars = re.compile("\s")
wordChars = re.compile("[a-z0-9._]", re.I)
importLine = re.compile("^([ \t]*)import\s+([a-z0-9._]+);", re.I | re.M)
packageLine = re.compile("package\s*([a-z0-9.]*);", re.I)
libLine = re.compile("([^:]*):[^\[]*\[(dev\:)?(.*)\]")
classpathLine = re.compile("Classpath : (.*)")
typeDecl = re.compile("(class|typedef|enum)\s+([A-Z][a-zA-Z0-9_]*)(<[a-zA-Z0-9_,]+>)?" , re.M )
libFlag = re.compile("-lib\s+(.*?)")
skippable = re.compile("^[a-zA-Z0-9_\s]*$")
inAnonymous = re.compile("[{,]\s*([a-zA-Z0-9_\"\']+)\s*:\s*$" , re.M | re.U )
comments = re.compile( "/\*(.*)\*/" , re.M )
extractTag = re.compile("<([a-z0-9_-]+).*\s(name|main)=\"([a-z0-9_./-]+)\"", re.I)
variables = re.compile("var\s+([^:;\s]*)", re.I)
functions = re.compile("function\s+([^;\.\(\)\s]*)", re.I)

class HaxeLib :

	available = {}
	basePath = None

	def __init__( self , name , dev , version ):
 		self.name = name
 		self.dev = dev
 		self.version = version
		self.classes = None
		self.packages = None
 
 		if self.dev :
 			self.path = self.version
 			self.version = "dev"
 		else : 
 			self.path = os.path.join( HaxeLib.basePath , self.name , ",".join(self.version.split(".")) )
 
 		#print(self.name + " => " + self.path)

	def extract_types( self ):
		if self.dev is True or ( self.classes is None and self.packages is None ):
			self.classes, self.packages = HaxeComplete.inst.extract_types( self.path )
		
		return self.classes, self.packages

	@staticmethod
	def get( name ) :
		if( name in HaxeLib.available.keys()):
			return HaxeLib.available[name]
		else :
			sublime.status_message( "Haxelib : "+ name +" project not installed" )
			return None

	@staticmethod
	def get_completions() :
		comps = []
		for l in HaxeLib.available :
			lib = HaxeLib.available[l]
			comps.append( ( lib.name + " [" + lib.version + "]" , lib.name ) )

		return comps

	@staticmethod
	def scan() :
		hlout, hlerr = runcmd( ["haxelib" , "config" ] )
		HaxeLib.basePath = hlout.strip()

		HaxeLib.available = {}

		hlout, hlerr = runcmd( ["haxelib" , "list" ] )

		for l in hlout.split("\n") :
			found = libLine.match( l )
			if found is not None :
				name, dev, version = found.groups()
				lib = HaxeLib( name , dev is not None , version )

				HaxeLib.available[ name ] = lib



HaxeLib.scan()

inst = None
class HaxeBuild :

	#auto = None
	targets = ["js","cpp","swf","swf9","neko","php"]
	nme_targets = ["flash","flash -debug","html5","cpp","ios -simulator","android","webos"]
	nme_target = "flash -debug"

	def __init__(self) :

		self.args = []
		self.main = None
		self.target = None
		self.output = "dummy.js"
		self.hxml = None
		self.nmml = None
		self.classpaths = []
		self.libs = []

	def to_string(self) :
		out = os.path.basename(self.output)
		if self.nmml is not None:
			return "{out} ({target})".format(self=self, out=out, target=HaxeBuild.nme_target);
		else:
			return "{out}".format(self=self, out=out);
		#return "{self.main} {self.target}:{out}".format(self=self, out=out);
	
	def make_hxml( self ) :
		outp = "# Autogenerated "+self.hxml+"\n\n"
		outp += "# "+self.to_string() + "\n"
		outp += "-main "+ self.main + "\n"
		for a in self.args :
			outp += " ".join( list(a) ) + "\n"
		
		d = os.path.dirname( self.hxml ) + "/"
		
		# relative paths
		outp = outp.replace( d , "")
		outp = outp.replace( "-cp "+os.path.dirname( self.hxml )+"\n", "")

		outp = outp.replace("--no-output " , "")
		outp = outp.replace("-v" , "")

		outp = outp.replace("dummy" , self.main.lower() )

		#print( outp )
		return outp.strip()

	def get_types( self ) :
		classes = []
		packs = []

		cp = []
		cp.extend( self.classpaths )

		for lib in self.libs :
			if lib is not None :
				cp.append( lib.path )

		for path in cp :
			c, p = HaxeComplete.inst.extract_types( path )
			classes.extend( c )
			packs.extend( p )

		classes.sort()
		packs.sort()
		return classes, packs


class HaxeInstallLib( sublime_plugin.WindowCommand ):
	def run(self):
		out,err = runcmd(["haxelib" , "search" , " "]);
		libs = out.splitlines()
		self.libs = libs[0:-1]

		self.window.show_quick_panel(libs,self.install)

	def install( self, i ):
		lib = self.libs[i]
		out,err = runcmd(["haxelib" , "install" , lib ])
		lines = out.splitlines()
		lines[1] = ""

		panel = self.window.get_output_panel("haxelib")
		edit = panel.begin_edit()
		panel.insert(edit, panel.size(), "\n".join(lines) )
		panel.end_edit( edit )
		self.window.run_command("show_panel",{"panel":"output.haxelib"})




class HaxeGenerateImport( sublime_plugin.TextCommand ):

	start = None
	size = None
	cname = None

	def get_end( self, src, offset ) :
		end = len(src)
		while offset < end:
			c = src[offset]
			offset += 1
			if not wordChars.match(c): break
		return offset - 1

	def get_start( self, src, offset ) :
		foundWord = 0
		offset -= 1
		while offset > 0:
			c = src[offset]
			offset -= 1
			if foundWord == 0:
				if spaceChars.match(c): continue
				foundWord = 1
			if not wordChars.match(c): break

		return offset + 2
	
	def is_membername( self, token ) :
		return token[0] >= "Z" or token == token.upper()

	def get_classname( self, view, src ) :
		loc = view.sel()[0]
		end = max(loc.a, loc.b)
		self.size = loc.size()
		if self.size == 0:
			end = self.get_end(src, end)
			self.start = self.get_start(src, end)
			self.size = end - self.start
		else:
			self.start = end - self.size

		self.cname = view.substr(sublime.Region(self.start, end)).rpartition(".")
		#print(self.cname)
		while not self.cname[0] == "" and self.is_membername(self.cname[2]):
			self.size -= 1 + len(self.cname[2])
			self.cname = self.cname[0].rpartition(".")

	def compact_classname( self, edit, view ) :
		view.replace(edit, sublime.Region(self.start, self.start+self.size), self.cname[2])
		view.sel().clear()
		loc = self.start + len(self.cname[2])
		view.sel().add(sublime.Region(loc, loc))

	def get_indent( self, src, index ) :
	
		if src[index] == "\n": return index + 1
		return index

	def insert_import( self, edit, view, src) :
		cname = "".join(self.cname)
		clow = cname.lower()
		last = None

		for imp in importLine.finditer(src):
			if clow < imp.group(2).lower():
				ins = "{0}import {1};\n".format(imp.group(1), cname)
				view.insert(edit, self.get_indent(src, imp.start(0)), ins)
				return
			last = imp

		if not last is None:
			ins = ";\n{0}import {1}".format(last.group(1), cname)
			view.insert(edit, last.end(2), ins)
		else:
			pkg = packageLine.search(src)
			if not pkg is None:
				ins = "\n\nimport {0};".format(cname)
				view.insert(edit, pkg.end(0), ins)
			else:
				ins = "import {0};\n\n".format(cname)
				view.insert(edit, 0, ins)

	def run( self , edit ) :
		complete = HaxeComplete.inst
		view = self.view
		src = view.substr(sublime.Region(0, view.size()))
		self.get_classname(view, src)
		
		if self.cname[1] == "": 
			sublime.status_message("Nothing to import")
			return

		self.compact_classname(edit, view)

		if re.search("import\s+{0}".format("".join(self.cname)), src):
			sublime.status_message("Already imported")
			return
		
		self.insert_import(edit, view, src)		


class HaxeDisplayCompletion( sublime_plugin.TextCommand ):
	
	def run( self , edit ) :
		#print("completing")
		view = self.view
		s = view.settings();
		
		view.run_command( "auto_complete" , {
			"api_completions_only" : True,
            "disable_auto_insert" : True,
            "next_completion_if_showing" : False
		} )

		

class HaxeInsertCompletion( sublime_plugin.TextCommand ):
	
	def run( self , edit ) :
		#print("insert completion")
		view = self.view

		view.run_command( "insert_best_completion" , {
			"default" : ".",
            "exact" : True
		} )



class HaxeRunBuild( sublime_plugin.TextCommand ):
	def run( self , edit ) :
		complete = HaxeComplete.inst
		view = self.view
		
		complete.run_build( view )


class HaxeSelectBuild( sublime_plugin.TextCommand ):
	def run( self , edit ) :
		complete = HaxeComplete.inst
		view = self.view
		
		complete.select_build( view )


class HaxeHint( sublime_plugin.TextCommand ):
	def run( self , edit ) :
		#print("haxe hint")
		
		complete = HaxeComplete.inst
		view = self.view
		
		sel = view.sel()
		for r in sel :
			comps = complete.get_haxe_completions( self.view , r.end() )
			#print(status);
			#view.set_status("haxe-status", status)
			#sublime.status_message(status)
			#if( len(comps) > 0 ) :
			#	view.run_command('auto_complete', {'disable_auto_insert': True})


class HaxeComplete( sublime_plugin.EventListener ):

	#folder = ""
	#buildArgs = []
	currentBuild = None
	selectingBuild = False
	builds = []
	errors = []

	currentCompletion = {
		"inp" : None,
		"outp" : None
	}

	stdPaths = []
	stdPackages = []
	#stdClasses = ["Void","Float","Int","UInt","Null","Bool","Dynamic","Iterator","Iterable","ArrayAccess"]
	stdClasses = []
	stdCompletes = []

	panel = None

	def __init__(self):
		HaxeComplete.inst = self

		out, err = runcmd( ["haxe", "-main", "Nothing", "-js", "nothing.js", "-v", "--no-output"] )
		#print(out)
		m = classpathLine.match(out)
		if m is not None :
			HaxeComplete.stdPaths = m.group(1).split(";")

		for p in HaxeComplete.stdPaths :
			if len(p) > 1 and os.path.exists(p) and os.path.isdir(p):
				for f in os.listdir( p ) :
					classes, packs = self.extract_types( p )
					HaxeComplete.stdClasses.extend( classes )
					HaxeComplete.stdPackages.extend( packs )

		#for cl in HaxeComplete.stdClasses :
		#	HaxeComplete.stdCompletes.append( ( cl + " [class]" , cl ))
		#for pack in HaxeComplete.stdPackages :
		#	HaxeComplete.stdCompletes.append( ( pack , pack ))


	def extract_types( self , path , depth = 0 ) :
		classes = []
		packs = []
		hasClasses = False

		for fullpath in glob.glob( os.path.join(path,"*.hx") ) : 
			f = os.path.basename(fullpath)
			cl, ext = os.path.splitext( f )
								
			if cl not in HaxeComplete.stdClasses:
				
				s = open( os.path.join( path , f ) , "r" )
				src = s.read() #comments.sub( s.read() , "" )
				
				clPack = "";
				for ps in packageLine.findall( src ) :
					clPack = ps
				
				if clPack == "" :
					packDepth = 0
				else:
					packDepth = len(clPack.split("."))

				for decl in typeDecl.findall( src ):
					t = decl[1]

					if( packDepth == depth and t == cl or cl == "StdTypes") :
						classes.append( t )
						hasClasses = True
		

		if hasClasses : 
			
			for f in os.listdir( path ) :
				
				cl, ext = os.path.splitext( f )
												
				if os.path.isdir( os.path.join( path , f ) ) and f not in HaxeComplete.stdPackages :
					packs.append( f )
					subclasses,subpacks = self.extract_types( os.path.join( path , f ) , depth + 1 )
					for cl in subclasses :
						classes.append( f + "." + cl )
					
					
		classes.sort()
		packs.sort()
		return classes, packs


	def highlight_errors( self , view ) :
		fn = view.file_name()
		regions = []

		for e in self.errors :
			if e["file"] == fn :
				l = e["line"]
				left = e["from"]
				right = e["to"]
				a = view.text_point(l,left)
				b = view.text_point(l,right)

				regions.append( sublime.Region(a,b))

				view.set_status("haxe-status" , "Error: " + e["message"] )
				
		view.add_regions("haxe-error" , regions , "invalid" , "dot" )

	def on_load( self, view ) :
		scopes = view.scope_name(view.sel()[0].end()).split()
		#sublime.status_message( scopes[0] )
		if 'source.haxe.2' not in scopes and 'source.hxml' not in scopes:
			return []
		
		self.generate_build(view)
		self.highlight_errors( view )
	
	def on_activated( self , view ) :
		scopes = view.scope_name(view.sel()[0].end()).split()
		#sublime.status_message( scopes[0] )
		if 'source.haxe.2' not in scopes and 'source.hxml' not in scopes:
			return []

		if 'source.haxe.2' in scopes :
			self.get_build(view)
			self.extract_build_args( view )
		
		self.generate_build(view)
		self.highlight_errors( view )

	def __on_modified( self , view ):
		win = sublime.active_window()
		if win is None :
			return None

		isOk = ( win.active_view().buffer_id() == view.buffer_id() )
		if not isOk :
			return None
		
		sel = view.sel()
		caret = 0
		for s in sel :
			caret = s.a
		
		if caret == 0 :
			return None

		if view.score_selector(caret,"source.haxe") == 0 or view.score_selector(caret,"string") > 0 or view.score_selector(caret,"comment") :
			return None

		src = view.substr(sublime.Region(0, view.size()))
		ch = src[caret-1]
		#print(ch)
		if ch not in ".(:, " :
			#print("here")
			view.run_command("haxe_display_completion")
		#else :
		#	view.run_command("haxe_insert_completion")


	def generate_build(self, view) :

		fn = view.file_name()

		if self.currentBuild is not None and fn == self.currentBuild.hxml and view.size() == 0 :	
			e = view.begin_edit()
			hxmlSrc = self.currentBuild.make_hxml()
			view.insert(e,0,hxmlSrc)
			view.end_edit(e)


	def select_build( self , view ) :
		self.extract_build_args( view , True )


	def find_nmml( self, folder ) :
		nmmls = glob.glob( os.path.join( folder , "*.nmml" ) )

		for build in nmmls:
			currentBuild = HaxeBuild()
			currentBuild.hxml = build
			currentBuild.nmml = build
			buildPath = os.path.dirname(build)

			# TODO delegate compiler options extractions to NME 3.2:
			# runcmd("nme diplay project.nmml nme_target")

			outp = "NME"
			f = open( build , "r+" )
			while 1:
				l = f.readline() 
				if not l : 
					break;
				m = extractTag.search(l)
				if not m is None:
					#print(m.groups())
					tag = m.group(1)
					name = m.group(3)
					if (tag == "app"):
						currentBuild.main = name
						mFile = re.search("\\b(file|title)=\"([a-z0-9_-]+)\"", l, re.I)
						if not mFile is None:
							outp = mFile.group(2)
					elif (tag == "haxelib"):
						currentBuild.libs.append( HaxeLib.get( name ) )
						currentBuild.args.append( ("-lib" , name) )
					elif (tag == "classpath"):
						currentBuild.classpaths.append( os.path.join( buildPath , name ) )
						currentBuild.args.append( ("-cp" , os.path.join( buildPath , name ) ) )
				else: # NME 3.2
					mPath = re.search("\\bpath=\"([a-z0-9_-]+)\"", l, re.I)
					if not mPath is None:
						#print(mPath.groups())
						path = mPath.group(1)
						currentBuild.classpaths.append( os.path.join( buildPath , path ) )
						currentBuild.args.append( ("-cp" , os.path.join( buildPath , path ) ) )
			
			outp = os.path.join( folder , outp )
			currentBuild.target = "cpp"
			currentBuild.args.append( ("--remap", "flash:nme") )
			currentBuild.args.append( ("-cpp", outp) )
			currentBuild.output = outp

			if currentBuild.main is not None :
				self.builds.append( currentBuild )


	def find_hxml( self, folder ) :
		hxmls = glob.glob( os.path.join( folder , "*.hxml" ) )

		for build in hxmls:

			currentBuild = HaxeBuild()
			currentBuild.hxml = build
			buildPath = os.path.dirname(build);

			# print("build file exists")
			f = open( build , "r+" )
			while 1:
				l = f.readline() 
				if not l : 
					break;
				if l.startswith("--next") :
					self.builds.append( currentBuild )
					currentBuild = HaxeBuild()
					currentBuild.hxml = build
					
				l = l.strip()
				if l.startswith("-main") :
					spl = l.split(" ")
					if len( spl ) == 2 :
						currentBuild.main = spl[1]
					else :
						sublime.status_message( "Invalid build.hxml : no Main class" )
				if l.startswith("-lib") :
					spl = l.split(" ")
					if len( spl ) == 2 :
						lib = HaxeLib.get( spl[1] )
						currentBuild.libs.append( lib )
					else :
						sublime.status_message( "Invalid build.hxml : lib not found" )
					
				for flag in [ "lib" , "D" , "swf-version" , "swf-header", "debug" , "-no-traces" , "-flash-use-stage" , "-gen-hx-classes" , "-remap" , "-no-inline" , "-no-opt" , "-php-prefix" , "-js-namespace" , "-interp" , "-macro" , "-dead-code-elimination" , "-remap" , "-php-front" , "-php-lib"] :
					if l.startswith( "-"+flag ) :
						currentBuild.args.append( tuple(l.split(" ") ) )
						
						break
				
				for flag in [ "resource" , "xml" , "x" , "swf-lib" ] :
					if l.startswith( "-"+flag ) :
						spl = l.split(" ")
						outp = os.path.join( folder , " ".join(spl[1:]) )
						currentBuild.args.append( ("-"+flag, outp) )
						
						break

				for flag in HaxeBuild.targets :
					if l.startswith( "-" + flag + " " ) :
						spl = l.split(" ")
						outp = os.path.join( folder , " ".join(spl[1:]) )
						currentBuild.args.append( ("-"+flag, outp) )
						
						currentBuild.target = flag
						currentBuild.output = outp
						break

				if l.startswith("-cp "):
					cp = l.split(" ")
					#view.set_status( "haxe-status" , "Building..." )
					cp.pop(0)
					classpath = " ".join( cp )
					currentBuild.classpaths.append( os.path.join( buildPath , classpath ) )
					currentBuild.args.append( ("-cp" , os.path.join( buildPath , classpath ) ) )
			
			if len(currentBuild.classpaths) == 0:
				currentBuild.classpaths.append( buildPath )
				currentBuild.args.append( ("-cp" , buildPath ) )
			
			if currentBuild.main is not None :
				self.builds.append( currentBuild )


	def extract_build_args( self , view , forcePanel = False ) :
		scopes = view.scope_name(view.sel()[0].end()).split()
		#sublime.status_message( scopes[0] )
		if 'source.haxe.2' not in scopes and 'source.hxml' not in scopes and 'source.nmml' not in scopes:
			return []
		
		self.builds = []

		fn = view.file_name()
		settings = view.settings()

		folder = os.path.dirname(fn)
		
		folders = view.window().folders()
		for f in folders:
			if f in fn :
				folder = f

		# settings.set("haxe-complete-folder", folder)
		self.find_hxml(folder)
		self.find_nmml(folder)
		
		if len(self.builds) == 1:
			sublime.status_message("There is only one build")
			self.set_current_build( view , int(0), forcePanel )

		elif len(self.builds) == 0 and forcePanel :
			sublime.status_message("No hxml or nmml file found")

			f = os.path.join(folder,"build.hxml")
			if self.currentBuild is not None :
				self.currentBuild.hxml = f

			#for whatever reason generate_build doesn't work without transient
			v = view.window().open_file(f,sublime.TRANSIENT) 

		elif len(self.builds) > 1 and forcePanel :
			buildsView = []
			for b in self.builds :
				#for a in b.args :
				#	v.append( " ".join(a) )
				buildsView.append( [b.to_string(), os.path.basename( b.hxml ) ] )

			self.selectingBuild = True
			sublime.status_message("Please select your build")
			view.window().show_quick_panel( buildsView , lambda i : self.set_current_build(view, int(i), forcePanel) , sublime.MONOSPACE_FONT )

		elif settings.has("haxe-build-id"):
			self.set_current_build( view , int(settings.get("haxe-build-id")), forcePanel )
		
		else:
			self.set_current_build( view , int(0), forcePanel )


	def set_current_build( self , view , id , forcePanel ) :
		#print("setting current build #"+str(id))
		#print( self.builds )
		if id < 0 or id >= len(self.builds) :
			id = 0
		
		view.settings().set( "haxe-build-id" , id )	

		if len(self.builds) > 0 :
			self.currentBuild = self.builds[id]
			view.set_status( "haxe-build" , self.currentBuild.to_string() )
		else:
			#self.currentBuild = None
			view.set_status( "haxe-build" , "No build" )
			
		self.selectingBuild = False

		if forcePanel and self.currentBuild is not None: # choose NME target
			if self.currentBuild.nmml is not None:
				sublime.status_message("Please select a NME target")
				view.window().show_quick_panel(HaxeBuild.nme_targets, lambda i : self.select_nme_target(i, view))


	def select_nme_target( self, i, view ):
		target = HaxeBuild.nme_targets[i]
		if self.currentBuild.nmml is not None:
			HaxeBuild.nme_target = target
			view.set_status( "haxe-build" , self.currentBuild.to_string() )


	def run_build( self , view ) :
		view.run_command("save")
		self.clear_output_panel(view)
		#view.set_status( "haxe-status" , "Building..." )
		err, comps, status = self.run_haxe( view )
		if status == "Build success":
			self.panel_output(view,status,"success")
		elif status != "Running...":
			self.panel_output( view , err , "invalid" )
		
		#print(status)
		view.set_status( "haxe-status" , status )
		#if not "success" in status :
			#sublime.error_message( err )

	def clear_output_panel(self, view) :
		win = view.window()
		self.panel = win.get_output_panel("haxe")

	def panel_output( self , view , text , scope = None ) :
		win = view.window()
		if self.panel is None :
			self.panel = win.get_output_panel("haxe")

		panel = self.panel
		
		edit = panel.begin_edit()
		region = sublime.Region(panel.size(),panel.size() + len(text))
		panel.insert(edit, panel.size(), text + "\n")
		panel.end_edit( edit )

		if scope is not None :
			icon = "dot"
			key = "haxe-" + scope
			regions = panel.get_regions( key );
			regions.append(region)
			panel.add_regions( key , regions , scope , icon )
		#print( err )
		win.run_command("show_panel",{"panel":"output.haxe"})

		return self.panel

	def get_toplevel_completion( self , src , src_dir , build ) :
		cl = []
		comps = [("trace","trace")]

		localTypes = typeDecl.findall( src )
		for t in localTypes :
			if t[1] not in cl:
				cl.append( t[1] )

		packageClasses, subPacks = self.extract_types( src_dir )
		for c in packageClasses :
			if c not in cl:
				cl.append( c )

		imports = importLine.findall( src )
		for i in imports :
			imp = i[1]
			dot = imp.rfind(".")+1
			clname = imp[dot:]
			cl.append( clname )
			#print( i )

		buildClasses , buildPacks = build.get_types()
		
		cl.extend( HaxeComplete.stdClasses )
		cl.extend( buildClasses )
		cl.sort();

		packs = []
		stdPackages = []
		#print("target : "+build.target)
		for p in HaxeComplete.stdPackages :
			#print(p)
			if p == "flash9" :
				p = "flash"
			if build.target is None or (p not in HaxeBuild.targets) or (p == build.target) :
				stdPackages.append(p)

		packs.extend( stdPackages )
		packs.extend( buildPacks )
		packs.sort()

		for v in variables.findall(src) :
			comps.append(( v + " [var]" , v ))
		
		for f in functions.findall(src) :
			if f not in ["new"] :
				comps.append(( f + " [function]" , f ))

		for c in cl :
			spl = c.split(".")
			if spl[0] == "flash9" :
				spl[0] = "flash"

			top = spl[0]
			#print(spl)
			
			clname = spl.pop()
			pack = ".".join(spl)
			display = clname
			if pack != "" :
				display += " [" + pack + "]"
			else :
				display += " [class]"
			
			spl.append(clname)
			cm = ( display , ".".join(spl) )
			if cm not in comps and ( build.target is None or (top not in HaxeBuild.targets) or (top == build.target) ) :
				comps.append( cm )
		
		for p in packs :
			cm = (p + " [package]",p)
			if cm not in comps :
				comps.append(cm)


		return comps


	def get_build( self , view ) :
		
		if self.currentBuild is None:
			fn = view.file_name()
			src_dir = os.path.dirname( fn )
			src = view.substr(sublime.Region(0, view.size()))
		
			build = HaxeBuild()
			build.target = "js"

			folder = os.path.dirname(fn)
			folders = view.window().folders()
			for f in folders:
				if f in fn :
					folder = f

			pack = []
			for ps in packageLine.findall( src ) :
				pack = ps.split(".")
				for p in reversed(pack) : 
					spl = os.path.split( src_dir )
					if( spl[1] == p ) :
						src_dir = spl[0]

			build.output = os.path.join(folder,"dummy.js")

			cl = os.path.basename(fn)
			cl = cl.encode('ascii','ignore')
			cl = cl[0:cl.rfind(".")]
			main = pack[0:]
			main.extend( [ cl ] )
			build.main = ".".join( main )

			build.args.append( ("-cp" , src_dir) )
			#build.args.append( ("-main" , build.main ) )

			build.args.append( ("-js" , build.output ) )
			build.args.append( ("--no-output" , "-v" ) )

			build.hxml = os.path.join( src_dir , "build.hxml")
			self.currentBuild = build
			
		return self.currentBuild	


	def run_nme( self, view, build ) :

		cmd = [ "haxelib", "run", "nme", "test", os.path.basename(build.nmml) ]
		target = HaxeBuild.nme_target.split(" ")
		cmd.extend(target)

		view.window().run_command("exec", {
			"cmd": cmd,
			"working_dir": os.path.dirname(build.nmml)
		})
		return ("" , [], "Running..." )


	def run_haxe( self, view , display = None , commas = 0 ) :

		build = self.get_build( view )
		settings = view.settings()

		autocomplete = display is not None

		if autocomplete is False and build.nmml is not None:
			return self.run_nme(view, build)
		
		fn = view.file_name()
		src = view.substr(sublime.Region(0, view.size()))
		src_dir = os.path.dirname(fn)
		tdir = os.path.dirname(fn)
		temp = os.path.join( tdir , os.path.basename( fn ) + ".tmp" )

		comps = []

		self.errors = []

		args = []
		
		#buildArgs = view.window().settings
		
		
		args.extend( build.args )	
			

		if not autocomplete :
			args.append( ("-main" , build.main ) )
		else:
			args.append( ("--display", display ) )
			args.append( ("--no-output" , "-v" ) )
			
		cmd = ["haxe"]
		for a in args :
			cmd.extend( list(a) )
		
		#print(cmd)
		res, err = runcmd( cmd, "" )
		
		if not autocomplete :
			self.panel_output( view , " ".join(cmd) )

		#print( "err: %s" % err )
		#print( "res: %s" % res )
		status = ""

		if (not autocomplete) and (build.hxml is None) :
			#status = "Please create an hxml file"
			self.extract_build_args( view , True )
		elif not autocomplete :
			# default message = build success
			status = "Build success"

		
		#print(err)	
		hints = []
		tree = None
		try :
			tree = ElementTree.XML( "<root>"+err+"</root>" )
		except xml.parsers.expat.ExpatError:
			print("invalid xml")
		
		if tree is not None :
			for i in tree.getiterator("type") :
				hint = i.text.strip()
				types = hint.split(" -> ")
				ret = types.pop()
				msg = "";
				
				if commas >= len(types) :
					if commas == 0 :
						msg = hint + ": No autocompletion available"
						#view.window().run_command("insert" , {'characters':")"})
						#comps.append((")",""))
					else:
						msg =  "Too many arguments."
				else :
					msg = ", ".join(types[commas:]) 

				if msg :
					#msg =  " ( " + " , ".join( types ) + " ) : " + ret + "      " + msg
					hints.append( msg )

			if len(hints) > 0 :
				status = " | ".join(hints)
				
			li = tree.find("list")
			if li is not None :
				for i in li.getiterator("i"):
					name = i.get("n")
					sig = i.find("t").text
					doc = i.find("d").text #nothing to do
					insert = name
					hint = name

					if sig is not None :
						types = sig.split(" -> ")
						ret = types.pop()

						if( len(types) > 0 ) :
							#cm = name + "("
							cm = name
							if len(types) == 1 and types[0] == "Void" :
								types = []
								#cm += ")"
								hint = name + "() : "+ ret
								insert = cm
							else:
								hint = name + "( " + " , ".join( types ) + " ) : " + ret
								if len(hint) > 40: # compact arguments
									hint = compactFunc.sub("(...)", hint);
								insert = cm
						else :
							hint = name + " : " + ret
					else :
						if re.match("^[A-Z]",name ) :
							hint = name + " [class]"
						else :
							hint = name + " [package]"

					#if doc is not None :
					#	hint += "\t" + doc
					#	print(doc)
					
					if len(hint) > 40: # compact return type
						m = compactProp.search(hint)
						if not m is None:
							hint = compactProp.sub(": " + m.group(1), hint)
					
					comps.append( ( hint, insert ) )

		if len(hints) == 0 and len(comps) == 0:
		
			err = err.replace( temp , fn )
			err = re.sub("\(display(.*)\)","",err)

			lines = err.split("\n")
			l = lines[0].strip()
			
			if len(l) > 0:
				status = l

			regions = []
			
			for infos in compilerOutput.findall(err) :
				infos = list(infos)
				f = infos.pop(0)
				l = int( infos.pop(0) )-1
				left = int( infos.pop(0) )
				right = infos.pop(0)
				if right != "" :
					right = int( right )
				else :
					right = left+1
				m = infos.pop(0)

				self.errors.append({
					"file" : f,
					"line" : l,
					"from" : left,
					"to" : right,
					"message" : m
				})
				
				if( f == fn ):
					status = m
				
				if not autocomplete :
					w = view.window()
					if not w is None :
						w.open_file(f+":"+str(l)+":"+str(right) , sublime.ENCODED_POSITION  )
				#if not autocomplete

			self.highlight_errors( view )
		#print(status)
		return ( err, comps, status )
	

	def on_query_completions(self, view, prefix, locations):
		pos = locations[0]
		scopes = view.scope_name(pos).split()
		offset = pos - len(prefix)
		comps = []
		if offset == 0 : 
			return comps
		#print(scopes)
		if 'source.hxml' in scopes:
			comps = self.get_hxml_completions( view , offset )
		
		if 'source.haxe.2' in scopes:
			comps = self.get_haxe_completions( view , offset )
			
		return comps
	
	def get_haxe_completions( self , view , offset ):

		src = view.substr(sublime.Region(0, view.size()))
		fn = view.file_name()
		src_dir = os.path.dirname(fn)
		tdir = os.path.dirname(fn)
		temp = os.path.join( tdir , os.path.basename( fn ) + ".tmp" )

		#find actual autocompletable char.
		toplevelComplete = False
		userOffset = completeOffset = offset
		prev = src[offset-1]
		commas = 0
		comps = []
		#print("prev : "+prev)
		if prev not in "(." :
			fragment = view.substr(sublime.Region(0,offset))
			prevDot = fragment.rfind(".")
			prevPar = fragment.rfind("(")
			prevComa = fragment.rfind(",")
			prevColon = fragment.rfind(":")
			prevBrace = fragment.rfind("{")
			prevSymbol = max(prevDot,prevPar,prevComa,prevBrace,prevColon)
			
			if prevSymbol == prevComa:
				closedPars = 0

				for i in range( prevComa , 0 , -1 ) :
					c = src[i]
					if c == ")" :
						closedPars += 1
					elif c == "(" :
						if closedPars < 1 :
							completeOffset = i+1
							break
						else :
							closedPars -= 1
					elif c == "," :
						if closedPars == 0 :
							commas += 1
				
			else :

				completeOffset = max( prevDot + 1, prevPar + 1 , prevColon + 1 )
				skipped = src[completeOffset:offset]
				toplevelComplete = skippable.search( skipped ) is None and inAnonymous.search( skipped ) is None
		
			
		#print(src[completeOffset-1])
		if src[completeOffset-1] in ":(," or toplevelComplete :
			#print("toplevel")
			comps = self.get_toplevel_completion( src , src_dir , self.get_build( view ) )
			#print(comps)
		
		offset = completeOffset
		
		if src[offset-1]=="." and src[offset-2] in ".1234567890" :
			#comps.append(("... [iterator]",".."))
			comps.append((".","."))

		if src[completeOffset-1] not in ".,(" or toplevelComplete:
			return comps

		if not os.path.exists( tdir ):
			os.mkdir( tdir )
			
		if os.path.exists( fn ):
			# copy saved file to temp for future restoring
			shutil.copy2( fn , temp )
		
		# write current source to file
		f = codecs.open( fn , "wb" , "utf-8" )
		f.write( src )
		f.close()

		inp = (fn,offset,commas)
		if self.currentCompletion["inp"] is None or inp != self.currentCompletion["inp"] :
			ret , comps , status = self.run_haxe( view , fn + "@" + str(offset) , commas )
			self.currentCompletion["outp"] = (ret,comps,status)
		else :
			ret, comps, status = self.currentCompletion["outp"]

		self.currentCompletion["inp"] = inp
		
		#print(ret)
		#print(status)
		#print(status)
		
		view.set_status( "haxe-status", status )

		#os.remove(temp)
		if os.path.exists( temp ) :
			shutil.copy2( temp , fn )
			os.remove( temp )
		else:
			# fn didn't exist in the first place, so we remove it
			os.remove( fn )
		
		#sublime.status_message("")

		return comps
			

	def get_hxml_completions( self , view , offset ):
		src = view.substr(sublime.Region(0, offset))
		currentLine = src[src.rfind("\n")+1:offset]
		m = libFlag.match( currentLine )
		if m is not None :
			return HaxeLib.get_completions()
		else :
			return []
	
	def savetotemp( self, path, src ):
		f = tempfile.NamedTemporaryFile( delete=False )
		f.write( src )
		return f

	
