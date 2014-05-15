from setuptools import setup, find_packages

setup(name='juju-tosca',
      version="0.2.1",
      classifiers=[
          'Intended Audience :: Developers',
          'Programming Language :: Python',
          'Operating System :: OS Independent'],
      author='Kapil Thangavelu',
      author_email='kapil.foss@gmail.com',
      description="Application topologies using OASIS TOSCA YAML Profile",
      long_description=open("README.rst").read(),
      url='https://github.com/kapilt/juju-tosca',
      license='GPL',
      packages=find_packages(),
      package_data={'juju_tosca': ['tosca_schema.yaml']},
      install_requires=["PyYAML"],
      entry_points={
          "console_scripts": [
              'juju-tosca = juju_tosca.cli:main']},
      )
