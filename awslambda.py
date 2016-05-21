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
from io import BytesIO
from zipfile import ZipFile
from pprint import pprint  # noqa


class AWSClient():
    """Common AWS methods for all AWS-based commands."""

    def get_aws_client(self, resource_name):
        """Return a boto3 resource client."""
        client = boto3.client(resource_name)
        return client

    def test_aws_credentials_exist(self):
        """Check if AWS credentials are available."""
        session = boto3.session.Session()
        if session.get_credentials():
            return True
        return False


class LambdaClient(AWSClient):
    """Common methods for Lambda commands."""

    def __init__(self, *arg):
        """Init Lambda client."""
        super()
        self.functions = []

    @property
    def client(self):
        """Return AWS Lambda boto3 client."""
        if not self.test_aws_credentials_exist():
            sublime.error_message(
                "AWS credentials not found. " +
                "Follow the instructions at " +
                "https://pypi.python.org/pypi/boto3/")
        if hasattr(self, '_lambda_client'):
            return self._lambda_client
        setattr(self, '_lambda_client', self.get_aws_client('lambda'))
        return self._lambda_client

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
        zipfile = ZipFile(BytesIO(url.content))
        # extract to temporary directory
        temp_dir_path = tempfile.mkdtemp()
        print('created temporary directory', temp_dir_path)
        zipfile.extractall(path=temp_dir_path)
        return temp_dir_path

    def _load_functions(self):
        paginator = self.client.get_paginator('list_functions')
        sublime.status_message("Fetching lambda functions...")
        response_iterator = paginator.paginate()
        self.functions = []
        for page in response_iterator:
            print(page['Functions'])
            for func in page['Functions']:
                self.functions.append(func)
        sublime.status_message("Lambda functions fetched.")

    def select_function(self, callback):
        """Prompt to select a function then calls callback(function)."""
        self._load_functions()
        if not self.functions:
            sublime.message_dialog("No lambda functions were found.")
            return
        func_list = []
        for func in self.functions:
            func_list.append([
                func['FunctionName'],
                func['Description'],
                "Last modified: {}".format(func['LastModified']),
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
        print("running")
        print(function)
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
        return os.path.join(package_path, ".sublime-lambda-info")

    def open_lambda_package_in_new_window(self, package_path, function):
        """Spawn a new sublime window to edit an unzipped lambda package."""
        # add a file to the directory to pass in our function info
        lambda_info_path = self.lambda_info_path(package_path)

        with open(lambda_info_path, 'w') as f:
            f.write(str(function))
        self.open_in_new_window(paths=[package_path], cmd="prepare_lambda_window")


class PrepareLambdaWindowCommand(sublime_plugin.WindowCommand, LambdaClient):
    """Called when a lambda package has been downloaded and extracted and opened in a new window."""

    def run(self):
        """Mark this project as being tied to a lambda function."""
        win = sublime.active_window()
        proj_data = win.project_data()
        # proj_data['lambda_function'] = url
        win.set_project_data(proj_data)


class LambdaSaveHookListener(sublime_plugin.EventListener, LambdaClient):
    """Listener for events pertaining to editing lambdas."""

    def on_post_save_async(self, view):
        """Sync modified lambda source."""
        # view.set_status("lambda_post_save", "lambda-saved")


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
