import json
import os
import re
import sys
import tarfile
from dataclasses import dataclass
from typing import Iterable

import requests


class DockerRegistoryClient:
    REGISTRY_ENDPOINT = 'https://registry-1.docker.io/v2'

    @dataclass(frozen=True)
    class RegistoryAuthTokenResponse:
        # https://docs.docker.com/registry/spec/auth/jwt/
        content: dict

        @property
        def token(self) -> str:
            return self.content['token']

    @dataclass(frozen=True)
    class ImageManifestResponse:
        # https://docs.docker.com/registry/spec/manifest-v2-1/
        content: dict

        @property
        def name(self) -> str:
            return self.content['name']

        @property
        def tag(self) -> str:
            return self.content['tag']

        @property
        def layer_digests(self) -> list:
            return [layer['blobSum'] for layer in self.content['fsLayers']]

    def get_image_pull_auth_token(self, library: str, image: str) -> RegistoryAuthTokenResponse:
        """
        認証トークンを取得する
        :param library:
        :param image:
        :return:
        """
        url = f'https://auth.docker.io/token?service=registry.docker.io&scope=repository:{library}/{image}:pull'
        print(f'Get authtoken, url: {url}')
        response = requests.get(url)
        response.raise_for_status()
        return self.RegistoryAuthTokenResponse(content=response.json())

    def get_manifest(self, library: str, image: str, tag: str) -> ImageManifestResponse:
        """
        マニフェストを取得する
        :param library:
        :param image:
        :param tag:
        :return:
        """
        # 各レイヤーをダウンロードする
        url = f'{self.REGISTRY_ENDPOINT}/{library}/{image}/manifests/{tag}'
        print(f'Downloading manifest, url: {url}')
        response = requests.get(
            url,
            headers={
                'Authorization': f'Bearer {self.get_image_pull_auth_token(library, image).token}'
            })
        response.raise_for_status()
        return self.ImageManifestResponse(content=response.json())

    def download_layer(self, library: str, image: str, layer_digest: str) -> Iterable[bytes]:
        """
        Docker イメージのレイヤーをダウンロードする
        :param library:
        :param image:
        :param layer_digest:
        :return:
        """
        # 各レイヤーをダウンロードする
        print(f'Fetching layer {layer_digest} ..')
        # レイヤーのファイルをダウンロードする
        response = requests.get(
            f'{self.REGISTRY_ENDPOINT}/{library}/{image}/blobs/{layer_digest}',
            stream=True,
            headers={
                'Authorization': f'Bearer {self.get_image_pull_auth_token(library, image).token}'
            },
        )
        response.raise_for_status()
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                yield chunk


class PullCommand:
    IMAGE_DATA_DIR = '/var/opt/app/images'

    @classmethod
    def execute(cls, library: str, image: str, tag: str):
        """
        docker pull コマンド
        :return:
        """
        # ファイルを保存する ディレクトリ
        base_dir = os.path.dirname('/var/opt/app/')
        images_dir = os.path.join(base_dir, 'images')
        if not os.path.exists(images_dir):
            os.makedirs(images_dir)

        # マニフェストを取得する
        client = DockerRegistoryClient()
        manifest = client.get_manifest(library, image, tag)

        image_name_friendly = f"{manifest.name.replace('/', '_')}_{manifest.tag}"
        image_base_dir = os.path.join(images_dir, image_name_friendly)

        # マニフェストの json を保存する
        with open(os.path.join(images_dir,
                               image_name_friendly + '.json'), 'w') as manifest_file:
            manifest_file.write(json.dumps(manifest.content, ensure_ascii=False, indent=2, sort_keys=True, separators=(',', ': ')))

        # docker イメージのレイヤーを保存するディレクトリを作成する
        # hoge/image_name/layers/contents
        image_layers_path = os.path.join(image_base_dir, 'layers')
        contents_path = os.path.join(image_layers_path, 'contents')
        if not os.path.exists(contents_path):
            os.makedirs(contents_path)

        # 各レイヤーをダウンロードする
        for digest in manifest.layer_digests:
            print('Fetching layer %s..' % digest)
            # ダウンロードしたレイヤーを tar として保存する
            local_layer_tar_name = os.path.join(image_layers_path, digest) + '.tar'
            with open(local_layer_tar_name, 'wb') as f:
                for chunk in client.download_layer(library, image, digest):
                    if chunk:
                        f.write(chunk)

            # tar を展開する
            with tarfile.open(local_layer_tar_name, 'r') as tar:
                # tar ファイルの中身を一部表示する
                for member in tar.getmembers()[:10]:
                    print('- ' + member.name)
                print('...')
                tar.extractall(str(contents_path))
                print('extract done')

        print(f'Save docker image to {image_base_dir}')


def main(image_name: str):
    # image 部分をパース
    m = re.match(r'((?P<library>[^/:]*)/)?(?P<image>[^/:]+)(:)?(?P<tag>[^/:]*)', image_name)
    if not m:
        print('invalid args')
        sys.exit(1)

    # library が指定されない場合は 'library' をセットする
    library = m.group('library') if m.group('library') else 'library'
    image = m.group('image')
    # tag が指定されない場合は 'latest' をセットする
    tag = m.group('tag') if m.group('tag') else 'latest'

    PullCommand.execute(library, image, tag)


if __name__ == '__main__':
    main(sys.argv[1])
