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
import requests
import subprocess
import tempfile
import os
import json
import re
import zipfile
import io
from pprint import pprint  # noqa

INFO_FILE_NAME = ".sublime-lambda-info"
AWS_PROFILE_NAME = None  # specify a boto configuration profile to use (for testing)


class AWSClient():
    """Common AWS methods for all AWS-based commands."""

    def get_aws_client(self, client_name):
        """Return a boto3 client with our session."""
        session = self.get_aws_session()
        client = session.client(client_name)
        return client

    def get_aws_session(self):
        """Custom AWS low-level session."""
        if hasattr(self, '_aws_session'):
            return getattr(self, '_aws_session')
        # waiting on: https://github.com/boto/boto3/issues/704#issuecomment-231459948
        # yay done
        session = boto3.session.Session(profile_name=AWS_PROFILE_NAME)
        setattr(self, '_aws_session', session)
        return session

    def test_aws_credentials_exist(self):
        """Check if AWS credentials are available."""
        session = self.get_aws_session()
        if session.get_credentials():
            return True
        return False


class LambdaClient(AWSClient):
    """Common methods for Lambda commands."""

    def __init__(self, *arg):
        """Init Lambda client."""
        super()
        self.functions = []

    def _clear_client(self):
        if hasattr(self, '_aws_session'):
            delattr(self, '_aws_session')
        if hasattr(self, '_lambda_client'):
            delattr(self, '_lambda_client')

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
        if hasattr(self, '_lambda_client'):
            return self._lambda_client
        setattr(self, '_lambda_client', self.get_aws_client('lambda'))
        return self._lambda_client

    def select_boto_profile(self):
        """Select a profile to use for our AWS session.

        Multiple profiles (access keys) can be defined in AWS credential configuration.
        """
        # TODO: implement this when boto3 has a way to actually list available profiles.
        # Currently, it does not.
        pass

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
        zip = zipfile.ZipFile(io.BytesIO(url.content))
        # extract to temporary directory
        temp_dir_path = tempfile.mkdtemp()
        print('created temporary directory', temp_dir_path)
        zip.extractall(path=temp_dir_path)
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
        for page in response_iterator:
            # print(page['Functions'])
            for func in page['Functions']:
                self.functions.append(func)
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
        v = self.window.create_output_panel("lambda_info_{}".format(function['FunctionName']))
        v.run_command("display_lambda_function_info", {'function': function})

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
        proj_data = view.window().project_data()
        if not proj_data or 'lambda_function' not in proj_data:
            return
        # okay we're saving a lambda project! let's sync it back up!
        func = proj_data['lambda_function']
        self.upload_code(view, func)


class ListFunctionsCommand(sublime_plugin.WindowCommand, LambdaClient):
    """Fetch functions."""

    def run(self):
        """Display choices in a quick panel."""
        self.select_function(self.display_function_info)

    # def selected(self, function):
    #     self.window.run_command(self.)


class DisplayLambdaFunctionInfoCommand(sublime_plugin.TextCommand, LambdaClient):
    """Insert info about a function into the current file."""

    def run(self, edit, function=None):
        """Ok."""
        self.download_function(function)


class TestLambdaEditCommand(sublime_plugin.WindowCommand, LambdaClient):
    """Test editing a lambda."""

    def run(self):
        """Grab zip from test URL."""
