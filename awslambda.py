"""Plugin for editing the source of a Lambda in Amazon Web Services.

Configuration: configure your access key and default region
  as shown on https://pypi.python.org/pypi/boto3/1.2.3

Required IAM roles:
  lambda:ListFunctions,
  lambda:UpdateFunctionCode,
  lambda:GetFunction
"""

import sublime
import sublime_plugin
import boto3
import botocore
import requests
import subprocess
import tempfile
import os
import json
import re
import zipfile
import io
import pprint
from contextlib import contextmanager
from base64 import b64decode

INFO_FILE_NAME = ".sublime-lambda-info"
SETTINGS_PATH = "awslambda"
DEBUG = False


def _dbg(*msgs):
    if DEBUG:
        print(msgs)


@contextmanager
def cd(newdir):
    """Change to a directory, change back when context exits."""
    prevdir = os.getcwd()
    os.chdir(os.path.expanduser(newdir))
    try:
        yield
    finally:
        os.chdir(prevdir)


class AWSClient():
    """Common AWS methods for all AWS-based commands."""

    def get_aws_client(self, client_name):
        """Return a boto3 client with our session."""
        session = self.get_aws_session()
        client = None
        try:
            client = session.client(client_name)
        except botocore.exceptions.NoRegionError:
            sublime.error_message("A region must be specified in your configuration.")
        return client

    def get_aws_session(self):
        """Custom AWS low-level session."""
        if '_aws_session' in globals():
            _dbg("_aws_session exists")
            return globals()['_aws_session']
        # load profile from settings
        profile_name = self.get_profile_name()
        if profile_name not in self.get_available_profiles():
            # this profile name appears to not exist
            _dbg("Got bogus AWS profile name {}, resetting...".format(profile_name))
            profile_name = None
        session = boto3.session.Session(profile_name=profile_name)
        globals()['_aws_session'] = session
        return session

    def get_available_profiles(self):
        """Return different configuration profiles available for AWS.

        c.f. https://github.com/boto/boto3/issues/704#issuecomment-231459948
        """
        sess = boto3.session.Session(profile_name=None)
        if not sess:
            return []
        if not hasattr(sess, 'available_profiles'):
            # old boto :/
            return sess._session.available_profiles
        return sess.available_profiles()

    def get_profile_name(self):
        """Get selected profile name."""
        return self._settings().get("profile_name")

    def test_aws_credentials_exist(self):
        """Check if AWS credentials are available."""
        session = boto3.session.Session()
        if session.get_credentials():
            return True
        return False

    def _settings(self):
        """Get settings for this plugin."""
        return sublime.load_settings(SETTINGS_PATH)


class LambdaClient(AWSClient):
    """Common methods for Lambda commands."""

    def __init__(self, *arg):
        """Init Lambda client."""
        super()
        self.functions = []

    def _clear_client(self):
        _dbg("Clearing client")
        if '_aws_session' in globals():
            del globals()['_aws_session']
            _dbg("deleted _aws_session")
        if '_lambda_client' in globals():
            del globals()['_lambda_client']
            _dbg("deleted _lambda_client")

    @property
    def client(self):
        """Return AWS Lambda boto3 client."""
        if not self.test_aws_credentials_exist():
            self._clear_client()
            sublime.error_message(
                "AWS credentials not found.\n" +
                "Please follow the instructions at\n" +
                "https://pypi.python.org/pypi/boto3/")
            raise Exception("AWS credentials needed")
        if '_lambda_client' in globals():
            _dbg("_lambda_client_exists")
            return globals()['_lambda_client']
        client = self.get_aws_client('lambda')
        globals()['_lambda_client'] = client
        return client

    def select_aws_profile(self, window):
        """Select a profile to use for our AWS session.

        Multiple profiles (access keys) can be defined in AWS credential configuration.
        """
        profiles = self.get_available_profiles()
        if len(profiles) <= 1:
            # no point in going any further eh
            return

        def profile_selected_cb(selected_index):
            if selected_index == -1:
                # cancelled
                return
            profile = profiles[selected_index]
            if not profile:
                return
            # save in settings
            self._settings().set("profile_name", profile)
            # clear the current session
            self._clear_client()
            window.status_message("Using AWS profile {}".format(profile))
        window.show_quick_panel(profiles, profile_selected_cb)

    def download_function(self, function):
        """Download source to a function and open it in a new window."""
        arn = function['FunctionArn']
        func_code_res = self.client.get_function(FunctionName=arn)
        url = func_code_res['Code']['Location']
        temp_dir_path = self.extract_zip_url(url)
        self.open_lambda_package_in_new_window(temp_dir_path, function)

    def extract_zip_url(self, file_url):
        """Fetch a zip file and decompress it.

        :returns: hash of filename to contents.
        """
        url = requests.get(file_url)
        with zipfile.ZipFile(io.BytesIO(url.content)) as zip:
            # extract to temporary directory
            temp_dir_path = tempfile.mkdtemp()
            print('created temporary directory', temp_dir_path)
            with cd(temp_dir_path):
                zip.extractall()  # to cwd
        return temp_dir_path

    def zip_dir(self, dir_path):
        """Zip up a directory and all of its contents and return an in-memory zip file."""
        out = io.BytesIO()
        zip = zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED)

        # files to skip
        skip_re = re.compile("\.pyc$")  # no compiled python files pls
        for root, dirs, files in os.walk(dir_path):
            # add dir itself (needed for empty dirs
            zip.write(os.path.join(root, "."))
            # add files
            for file in files:
                file_path = os.path.join(root, file)
                in_zip_path = file_path.replace(dir_path, "", 1).lstrip("\\/")
                print("Adding file to lambda zip archive: '{}'".format(in_zip_path))
                if skip_re.search(in_zip_path):  # skip this file?
                    continue
                zip.write(file_path, in_zip_path)
        zip.close()
        if False:
            # debug
            zip.printdir()
        return out

    def upload_code(self, view, func):
        """Zip the temporary directory and upload it to AWS."""
        print(func)
        sublime_temp_path = func['sublime_temp_path']
        if not sublime_temp_path or not os.path.isdir(sublime_temp_path):
            print("error: failed to find temp lambda dir")
        # create zip archive, upload it
        try:
            view.set_status("lambda", "Creating lambda archive...")
            print("Creating zip archive...")
            zip_data = self.zip_dir(sublime_temp_path)  # create in-memory zip archive of our temp dir
            zip_bytes = zip_data.getvalue()  # read contents of BytesIO buffer
        except Exception as e:
            # view.show_popup("<h2>Error saving</h2><p>Failed to save: {}</p>".format(html.escape(e)))
            self.display_error("Error creating zip archive for upload: {}".format(e))
            view.set_status("lambda", "Failed to save lambda")
        else:
            # zip success?
            if zip_bytes:
                print("Created zip archive, len={}".format(len(zip_bytes)))
                # upload time
                try:
                    print("Uploading lambda archive...")
                    res = self.client.update_function_code(
                        FunctionName=func['FunctionArn'],
                        ZipFile=zip_bytes,
                    )
                except Exception as e:
                    self.display_error("Error uploading lambda: {}".format(e))
                    view.set_status("lambda", "Failed to upload lambda")
                else:
                    print("Upload successful.")
                    view.set_status("lambda", "Lambda uploaded as {} [{} bytes]".format(res['FunctionName'], res['CodeSize']))
            else:
                # got empty zip archive?
                view.set_status("lambda", "Failed to save lambda")

    def _load_functions(self, quiet=False):
        paginator = self.client.get_paginator('list_functions')
        if not quiet:
            sublime.status_message("Fetching lambda functions...")
        response_iterator = paginator.paginate()
        self.functions = []
        try:
            for page in response_iterator:
                # print(page['Functions'])
                for func in page['Functions']:
                    self.functions.append(func)
        except botocore.exceptions.ClientError as cerr:
            # display error fetching functions
            if not quiet:
                sublime.error_message(cerr.response['Error']['Message'])
            raise cerr
        if not quiet:
            sublime.status_message("Lambda functions fetched.")

    def select_function(self, callback):
        """Prompt to select a function then calls callback(function)."""
        self._load_functions()
        if not self.functions:
            sublime.message_dialog("No lambda functions were found.")
            return
        func_list = []
        for func in self.functions:
            last_mod = func['LastModified']  # ugh
            # last_mod = last_mod.strftime("%Y-%m-%d %H:%M")
            func_list.append([
                func['FunctionName'],
                func['Description'],
                "Last modified: {}".format(last_mod),
                "Runtime: {}".format(func['Runtime']),
                "Size: {}".format(func['CodeSize']),
            ])

        def selected_cb(selected_index):
            if selected_index == -1:
                # cancelled
                return
            function = self.functions[selected_index]
            if not function:
                sublime.error_message("Unknown function selected.")
            callback(function)
        self.window.show_quick_panel(func_list, selected_cb)

    def display_function_info(self, function):
        """Create an output panel with the function details."""
        if not isinstance(self, sublime_plugin.WindowCommand):
            raise Exception("display_function_info must be called on a WindowCommand")
        # v = self.window.create_output_panel("lambda_info_{}".format(function['FunctionName']))
        nv = self.window.new_file()
        nv.view.set_scratch(True)
        nv.run_command("display_function_info", {'function': function})

    def edit_function(self, function):
        """Edit a function's source."""
        if not isinstance(self, sublime_plugin.WindowCommand):
            raise Exception("edit_function must be called on a WindowCommand")
        nv = self.window.create_output_panel("lambda_info_{}".format(function['FunctionName']))
        nv.view.set_scratch(True)
        nv.run_command("edit_function", {'function': function})

    def open_in_new_window(self, paths=[], cmd=None):
        """Open paths in a new sublime window."""
        # from wbond https://github.com/titoBouzout/SideBarEnhancements/blob/st3/SideBar.py#L1916
        items = []

        executable_path = sublime.executable_path()

        if sublime.platform() == 'osx':
            app_path = executable_path[:executable_path.rfind(".app/") + 5]
            executable_path = app_path + "Contents/SharedSupport/bin/subl"
        items.append(executable_path)
        if cmd:
            items.extend(['--command', cmd])
        items.extend(paths)
        subprocess.Popen(items)

    def lambda_info_path(self, package_path):
        """Return path to the lambda info file for a downloaded package."""
        return os.path.join(package_path, INFO_FILE_NAME)

    def open_lambda_package_in_new_window(self, package_path, function):
        """Spawn a new sublime window to edit an unzipped lambda package."""
        # add a file to the directory to pass in our function info
        lambda_info_path = self.lambda_info_path(package_path)

        function['sublime_temp_path'] = package_path
        with open(lambda_info_path, 'w') as f:
            f.write(json.dumps(function))
        self.open_in_new_window(paths=[package_path], cmd="prepare_lambda_window")

    def invoke_function(self, func):
        """Invoke a lambda function.

        :returns: return_object, log_output, error
        """
        payload = {'sublime': True}
        res = self.client.invoke(
            FunctionName=func['FunctionName'],
            InvocationType='RequestResponse',  # synchronous
            LogType='Tail',  # give us last 4kb output in x-amz-log-result
            Payload=json.dumps(payload),
        )
        # if res['FunctionError']:
        #     self.display_error("Failed to invoke function: " + res['FunctionError'])
        #     return

        # return value from the lambda
        res_payload = res['Payload']
        if res_payload:
            res_payload = res_payload.read()
        # output
        res_log = res['LogResult']
        if res_log:
            res_log = b64decode(res_log).decode('utf-8')
        err = None
        if 'FunctionError' in res:
            err = res['FunctionError']
        return res_payload, res_log, err

    def invoke_function_test(self, function_name):
        """Ignore for now."""
        self.invoke_function()

    def get_window_function(self, window):
        """Try to see if there is a function associated with this window.

        :returns: function info dict.
        """
        proj_data = window.project_data()
        if not proj_data or 'lambda_function' not in proj_data:
            return
        func = proj_data['lambda_function']
        return func

    def get_view_function(self, view):
        """Try to see if there is a function associated with this view."""
        win = view.window()
        return self.get_window_function(win)

    def display_error(self, err):
        """Pop up an error message to the user."""
        sublime.message_dialog(err)


class PrepareLambdaWindowCommand(sublime_plugin.WindowCommand, LambdaClient):
    """Called when a lambda package has been downloaded and extracted and opened in a new window."""

    def run(self):
        """Mark this project as being tied to a lambda function."""
        win = self.window
        lambda_file_name = os.path.join(win.folders()[0], INFO_FILE_NAME)
        if not os.path.isfile(lambda_file_name):
            print(lambda_file_name + " does not exist")
            return
        lambda_file = open(lambda_file_name, 'r')
        func_info_s = lambda_file.read()
        lambda_file.close()
        if not func_info_s:
            print("Failed to read lambda file info")
        func_info = json.loads(func_info_s)
        proj_data = win.project_data()
        proj_data['lambda_function'] = func_info
        win.set_project_data(proj_data)

        # open default func file if it exists
        default_function_file = os.path.join(win.folders()[0], 'lambda_function.py')
        if os.path.isfile(default_function_file):
            win.open_file(default_function_file)


class LambdaSaveHookListener(sublime_plugin.EventListener, LambdaClient):
    """Listener for events pertaining to editing lambdas."""

    def on_post_save_async(self, view):
        """Sync modified lambda source."""
        func = self.get_view_function(view)
        if not func:
            return
        # okay we're saving a lambda project! let's sync it back up!
        self.upload_code(view, func)


class SelectEditFunctionCommand(sublime_plugin.WindowCommand, LambdaClient):
    """Fetch functions."""

    def run(self):
        """Display choices in a quick panel."""
        self.select_function(self.download_function)


class SelectGetFunctionInfoCommand(sublime_plugin.WindowCommand, LambdaClient):
    """Display some handy info about a function."""

    def run(self):
        """Display choices in a quick panel."""
        self.select_function(self.display_function_info)


class InvokeFunctionCommand(sublime_plugin.WindowCommand, LambdaClient):
    """Invoke current function."""

    def run(self):
        """Display function invocation result in a new file."""
        window = self.window
        func = self.get_window_function(window)
        if not func:
            self.display_error("No function is associated with this window.")
            return
        result, result_log, error_status = self.invoke_function(func)
        # display output
        nv = self.window.new_file()
        nv.set_scratch(True)
        fargs = dict(
            function=func,
            result=result.decode("utf-8"),
            result_log=result_log,
            error_status=error_status
        )
        nv.run_command("display_invocation_result", fargs)

    def is_enabled(self):
        """Enable or disable option, depending on if the current window is associated with a function."""
        func = self.get_window_function(self.window)
        if not func:
            return False
        return True


class EditFunctionInfoCommand(sublime_plugin.TextCommand, LambdaClient):
    """Open editor for source of a function."""

    def run(self, edit, function=None):
        """Ok."""
        self.download_function(function)


class DisplayFunctionInfoCommand(sublime_plugin.TextCommand, LambdaClient):
    """Insert info about a function into the current view."""

    def run(self, edit, function=None):
        """Ok."""
        pp = pprint.PrettyPrinter(indent=4)
        self.view.insert(edit, self.view.text_point(0, 0), pp.pformat(function))


class DisplayInvocationResultCommand(sublime_plugin.TextCommand, LambdaClient):
    """Display a function's results in this view."""

    def run(self, edit, function=None, result=None, result_log=None, error_status=None):
        """Ok."""
        err = ""
        if error_status:
            err = "\nError handled status: {}\n".format(error_status)
        out = """{funcname} Results
{err}
Log output: {log}

Result: {res}""".format(funcname=function['FunctionName'], res=result, log=result_log, err=err)
        self.view.insert(edit, self.view.text_point(0, 0), out)


class TestLambdaEditCommand(sublime_plugin.WindowCommand, LambdaClient):
    """Test editing a lambda."""

    def run(self):
        """Grab zip from test URL."""


class SelectProfileCommand(sublime_plugin.WindowCommand, LambdaClient):
    """Select an AWS configuration profile to use and save in settings."""

    def run(self):
        """Display choices in a quick panel."""
        self.select_aws_profile(self.window)

    def is_enabled(self):
        """Must have multiple profiles to select one."""
        profiles = self.get_available_profiles()
        if len(profiles) > 1:
            return True
        return False
