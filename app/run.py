import os
import re
import stat
import sys
import uuid
from typing import List

import linux
from dataclasses import dataclass


@dataclass(frozen=True)
class Image:
    library: str
    image: str
    tag: str


@dataclass(frozen=True)
class ContainerInitParams:
    image: Image
    command: List[str]
    container_id: str


@dataclass(frozen=True)
class ContainerDir:
    root_dir: str
    rw_dir: str
    work_dir: str


class ContainerExecuter:
    IMAGE_DATA_DIR = '/var/opt/app/images'
    CONTAINER_DATA_DIR = '/var/opt/app/container'

    def execute(self, init_params: ContainerInitParams):
        """
        指定されたパラメータでコンテナを起動する
        :param init_params:
        :return:
        """
        # ホスト名をコンテナ ID にする
        linux.sethostname(init_params.container_id)

        # ホストのマウントテーブルを汚さないように / をプライベートマウントする
        linux.mount(None, '/', None, linux.MS_PRIVATE | linux.MS_REC, None)

        # コンテナのディレクトリを初期化し、ルートディレクトリを変更する
        container_dir = self._create_container_root_dir(init_params.container_id)
        print(f'Created a new root fs for our container: {container_dir}')
        self._mount_image_dir(init_params.image, container_dir)
        self._init_system_dir(container_dir.root_dir)
        self._change_root_dir(container_dir.root_dir)

        # コンテナでコマンドを実行する
        os.execvp(init_params.command[0], init_params.command)

    def _create_container_root_dir(self, container_id: str) -> ContainerDir:
        """
        コンテナ用のルートディレクトリを作成する
        :param container_id:
        :return:
        """
        container_data_base_dir = self._get_container_data_base_path(container_id, self.CONTAINER_DATA_DIR)
        container_rootfs_dir = os.path.join(container_data_base_dir, 'rootfs')
        container_cow_rw_dir = os.path.join(container_data_base_dir, 'cow_rw')
        container_cow_workdir = os.path.join(container_data_base_dir, 'cow_workdir')

        for d in (container_rootfs_dir, container_cow_rw_dir, container_cow_workdir):
            if not os.path.exists(d):
                os.makedirs(d)

        return ContainerDir(
            root_dir=container_rootfs_dir,
            rw_dir=container_cow_rw_dir,
            work_dir=container_cow_workdir)

    def _mount_image_dir(self, image: Image, container_dir: ContainerDir):
        """
        Docker イメージをマウントする
        :param image:
        :param container_dir:
        :return:
        """
        image_path = self._get_image_base_path(image, self.IMAGE_DATA_DIR)
        image_root = os.path.join(image_path, 'layers/contents')

        # オーバーレイ FS としてマウントする
        linux.mount(
            'overlay',
            container_dir.root_dir,
            'overlay',
            linux.MS_NODEV,
            f"lowerdir={image_root},upperdir={container_dir.rw_dir},workdir={container_dir.work_dir}"
        )

    def _init_system_dir(self, container_root_dir: str):
        """
        システム用のディレクトリを初期化する
        :param container_root_dir:
        :return:
        """
        proc_dir = os.path.join(container_root_dir, 'proc')
        sysfs_dir = os.path.join(container_root_dir, 'sys')
        dev_dir = os.path.join(container_root_dir, 'dev')
        for d in (proc_dir, sysfs_dir, dev_dir):
            if not os.path.exists(d):
                os.makedirs(d)

        # コンテナのルートディレクトリ配下に /proc, /sys, /dev をマウントする
        linux.mount('proc', proc_dir, 'proc', 0, '')
        linux.mount('sysfs', sysfs_dir, 'sysfs', 0, '')
        linux.mount('tmpfs', dev_dir, 'tmpfs',
                    linux.MS_NOSUID | linux.MS_STRICTATIME, 'mode=755')

        # デバイスをマウントする
        devpts_path = os.path.join(container_root_dir, 'dev', 'pts')
        if not os.path.exists(devpts_path):
            os.makedirs(devpts_path)
            linux.mount('devpts', devpts_path, 'devpts', 0, '')

        self._init_devices(os.path.join(container_root_dir, 'dev'))

    def _init_devices(self, dev_path):
        for i, dev in enumerate(['stdin', 'stdout', 'stderr']):
            os.symlink('/proc/self/fd/%d' % i, os.path.join(dev_path, dev))
        os.symlink('/proc/self/fd', os.path.join(dev_path, 'fd'))

        # その他基本的なデバイスを追加する
        devices = {
            'null': (stat.S_IFCHR, 1, 3),
            'zero': (stat.S_IFCHR, 1, 5),
            'random': (stat.S_IFCHR, 1, 8),
            'urandom': (stat.S_IFCHR, 1, 9),
            'console': (stat.S_IFCHR, 136, 1),
            'tty': (stat.S_IFCHR, 5, 0),
            'full': (stat.S_IFCHR, 1, 7)
        }

        for device, (dev_type, major, minor) in devices.items():
            os.mknod(os.path.join(dev_path, device),
                     0o666 | dev_type, os.makedev(major, minor))

    def _get_image_base_path(self, image: Image, image_dir: str) -> str:
        return os.path.join(image_dir, f'{image.library}_{image.image}_{image.tag}')

    def _get_container_data_base_path(self, container_id: str, base_path: str):
        return os.path.join(base_path, container_id)

    def _change_root_dir(self, container_root_dir: str):
        """
        コンテナ内のルートディレクトリを変更する
        :param container_root_dir:
        :return:
        """
        old_root = os.path.join(container_root_dir, 'old_root')
        os.makedirs(old_root)
        linux.pivot_root(container_root_dir, old_root)

        os.chdir('/')

        linux.umount2('/old_root', linux.MNT_DETACH)
        os.rmdir('/old_root')


class RunCommand:
    @classmethod
    def execute(cls, init_params: ContainerInitParams):
        flags = (linux.CLONE_NEWPID | linux.CLONE_NEWNS | linux.CLONE_NEWUTS |
                 linux.CLONE_NEWNET)
        # 子プロセスを起動してコンテナを実行する
        pid = linux.clone(ContainerExecuter().execute, flags, (init_params,))

        # 子プロセスが終了するまで待つ
        _, status = os.waitpid(pid, 0)
        print('{} exited with status {}'.format(pid, status))


def main(args):
    # コマンド実行時の引数: python run.py <image_name> <command>
    m = re.match(r'((?P<library>[^/: ]*)/)?(?P<image>[^/: ]+)(:(?P<tag>[^/: ]*))?', args[1])
    if not m:
        print('invalid args')
        sys.exit(1)

    # library の指定がない場合は "library" をセット
    library = m.group('library') if m.group('library') else 'library'
    image = m.group('image')
    # tag の指定がない場合は "latest" をセット
    tag = m.group('tag') if m.group('tag') else 'latest'
    command = args[2:]

    RunCommand.execute(
        ContainerInitParams(
            image=Image(
                library=library,
                image=image,
                tag=tag,
            ),
            command=command,
            container_id=str(uuid.uuid4()),
        )
    )


if __name__ == '__main__':
    main(sys.argv)
