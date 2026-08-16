#!/usr/bin/env python3
"""
Setup script for SIP Manager - Pure Kamailio Web Management UI.

Usage:
    python3 setup.py install
    or
    pip3 install .
"""

from setuptools import setup, find_packages

setup(
    name='sipman',
    version='1.0.0',
    description='Lightweight Flask web management UI for Kamailio SIP proxy',
    long_description=open('README.md').read() if __import__('os').path.exists('README.md') else '',
    long_description_content_type='text/markdown',
    author='SIP Manager',
    license='GPL v3',
    python_requires='>=3.9',
    py_modules=['app'],
    install_requires=[
        'Flask>=2.3.0',
        'PyJWT>=2.7.0',
        'bcrypt>=4.0.0',
        'mysql-connector-python>=8.1.0',
        'gunicorn>=21.2.0',
    ],
    entry_points={
        'console_scripts': [
            'sipman=app:main',
        ],
    },
    classifiers=[
        'Development Status :: 4 - Beta',
        'Environment :: Web Environment',
        'Framework :: Flask',
        'Intended Audience :: System Administrators',
        'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
        'Operating System :: POSIX :: Linux',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.9',
        'Topic :: Internet Phone / VoIP',
        'Topic :: System :: Networking',
    ],
)
