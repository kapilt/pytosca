from setuptools import setup, find_packages

setup(name='pytosca',
      version="0.2.1",
      classifiers=[
          'Intended Audience :: Developers',
          'Programming Language :: Python',
          'License :: OSI Approved :: Apache Software License',
          'Operating System :: OS Independent'],
      author='Kapil Thangavelu',
      author_email='kapil.foss@gmail.com',
      description="Application topologies using OASIS TOSCA YAML Profile",
      long_description=open("README.rst").read(),
      url='https://github.com/kapilt/pytosca',
      license='Apache',
      packages=find_packages(),
      package_data={'pytosca': ['tosca_schema.yaml']},
      install_requires=["PyYAML"],
      )
