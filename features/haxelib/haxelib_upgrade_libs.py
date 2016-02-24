import sublime
import sublime_plugin

try: # Python 3
    from ..haxe_helper import runcmd
    from ..haxe_paths import haxelib_path
except (ValueError): # Python 2
    from haxe_helper import runcmd
    from haxe_paths import haxelib_path

#todo : This is now interactive so upgrade is harder this way.
#We could fetch the list of installed, manually run haxelib update over each
#or rather maybe we can show a list of AVAILABLE updates rather than upgrade all
#with the option to pick them from the quick panel
#{ "caption": "Haxelib: Upgrade all", "command": "haxelib_upgrade_libs" },
class HaxelibUpgradeLibs( sublime_plugin.WindowCommand ):
    def run(self):
        out,err = runcmd([haxelib_path() , "upgrade"]);

        self.window.show_quick_panel(out.splitlines(), None)
