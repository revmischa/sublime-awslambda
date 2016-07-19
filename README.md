Sublime Text 3 plugin for editing AWS Lambda function sources easily.

## Setup
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

## Demo Video
<a href="http://www.youtube.com/watch?feature=player_embedded&v=v0HOn66tS2U
" target="_blank"><img src="http://img.youtube.com/vi/v0HOn66tS2U/0.jpg" 
alt="Demo Video" width="240" height="180" border="10" /></a>
