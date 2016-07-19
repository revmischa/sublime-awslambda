Sublime Text 3 plugin for editing AWS Lambda function sources easily.

# Setup
To use this plugin you will need to configure AWS with your access key ID and secret.

### Credentials
If you use the AWS command-line interface [you can run `aws configure` to set up your credentials](http://boto3.readthedocs.io/en/latest/guide/configuration.html).  
They will be stored in `~/.aws/credentials`.

### Boto
[Or you can configure boto](https://pypi.python.org/pypi/boto3/), the official AWS python client library.  
Create a file `~/.boto` with your key and secret:
```
[Credentials]
aws_access_key_id = AKNGOINAGBQOWGQNW
aws_secret_access_key = GEIOWGNQAVIONGhg10g08GOAG/GAing2eingAn
```

# Installing The Plugin

* Sublime Package Manager
You must [install the sublime package manager](https://packagecontrol.io/installation) if you don't have it already.
* Select "Install Package" from the command palette and select "AWS Lambda"

### Video Instructions
Here's a short video showing how to install sublime package manager and the AWS Lambda plugin:
<a href="http://www.youtube.com/watch?feature=player_embedded&v=2cnm7HwEu4k
" target="_blank"><img src="http://img.youtube.com/vi/2cnm7HwEu4k/0.jpg" 
alt="Installation Video" width="240" height="180" border="10" /></a>


# Demo Video
### Plugin In Action!
<a href="http://www.youtube.com/watch?feature=player_embedded&v=v0HOn66tS2U
" target="_blank"><img src="http://img.youtube.com/vi/v0HOn66tS2U/0.jpg" 
alt="Demo Video" width="240" height="180" border="10" /></a>
