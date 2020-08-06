# build-docker-from-scratch
Build docker from scratch by Python!

# Requirements
- Vagrant
- Virtualbox

# Setup

### 1. Initialize vagrant machine
```
$ vagrant up
```

### 2. Install dependencies modules

Login to vagrant machine, and switch user to root.

```
$ vagrant ssh
$ sudo su -
```

Install Python dependencies modules.
```
$ cd /vagrant
$ pipenv install --system
```

Build and install Linux syscall wrapper module.
```
$ cd /vagrant/app/linux/
$ python3 setup.py install
```

Verify Linux module installation.
```
$ pip3 list | grep linux
> linux               1.0
```

# How to use

## Docker pull

Execute `pull.py` like `docker pull`.
```
$ python3 pull.py busybox
```

Pulled Docker image data is saved into under `/var/opt/app/images/`.
```
$ ls /var/opt/app/images/
library_busybox_latest  library_busybox_latest.json
```

## Docker run

Execute `run.py` like `docker run`.
```
$ python3 run.py busybox sh
> / # hostname
> 7a16f4bc-9314-4634-8406-aff516b7d3a3
```

## NOTE
You should execute there command as root.

### References
- https://github.com/Fewbytes/rubber-docker
- https://github.com/tonybaloney/mocker

