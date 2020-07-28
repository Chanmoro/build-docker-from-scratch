# -*- mode: ruby -*-
# vi: set ft=ruby :

Vagrant.configure("2") do |config|
  config.vm.box = "ubuntu/bionic64"
  config.vm.provider "virtualbox" do |vb|
    vb.gui = false
    vb.name = "build-docker-from-scratch"
    vb.memory = "1024"
    vb.cpus = 2
  end

  config.vm.provision "shell", inline: <<-SHELL
    apt update
    apt upgrade
    apt install -y python3-distutils python3-pip
    pip3 install pipenv
  SHELL

end
