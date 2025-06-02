"""Setup script for building Cython extensions."""

from setuptools import setup, Extension
from Cython.Build import cythonize
import numpy as np

extensions = [
    Extension(
        "signals_fast",
        ["signals_fast.pyx"],
        include_dirs=[np.get_include()],
        extra_compile_args=["-O3", "-march=native", "-ffast-math"],
        language="c",
    )
]

setup(
    name="nanohft_fast",
    ext_modules=cythonize(
        extensions,
        compiler_directives={
            'language_level': 3,
            'boundscheck': False,
            'wraparound': False,
            'nonecheck': False,
            'cdivision': True,
            'profile': False,
        }
    ),
    zip_safe=False,
)