# SPDX-FileCopyrightText: 2026 Robert Bosch GmbH
# SPDX-FileContributor: Tolga Dalman
#
# SPDX-License-Identifier: MIT

# CMake file for mingw32-w64 compiler (tested with https://winlibs.com/)
# Make sure that compiler executables (gcc, g++, ld, ...) are set in the PATH
# environment variable.

# explicitly setting this variable to False to indicate that we are compiling
# natively.
set(CMAKE_CROSSCOMPILING False)

list(APPEND CMAKE_PREFIX_PATH "${CMAKE_STAGING_PREFIX}/usr")

# setting compiler and linker flags.
# CACHE STRING "" FORCE overrides any defaults from CMake (e.g., -O3 -DNDEBUG)


# Security-related flags
# -fstack-protector-all: add canaries to all variables on stack
# -D_FORTIFY_SOURCE=1: use hardened variant of LIBC functions
# -> not used here because Ubuntu 16.04 and higher define this flag per default
# -Wshadow: warn when a variable is shadowing from upper context layers
# -Wstack-protector: warn for stack-protector problems
set(RBBUILD_SECURITY_C_FLAGS "-fstack-protector-all -Wshadow -Wstack-protector")

# C flags
# Contents of *_RELEASE and *_DEBUG parameters are appended according to the
# selected configuration
# -fno-semantic-interposition: do not allow to intercept symbols from libraries using LD_PRELOAD.
set(CMAKE_C_FLAGS         "${RBBUILD_SECURITY_C_FLAGS} -march=native -O2 -W -Wall -fdiagnostics-color=always"  CACHE STRING "" FORCE)
set(CMAKE_C_FLAGS_RELEASE "-s -fno-semantic-interposition"    CACHE STRING "" FORCE)
set(CMAKE_C_FLAGS_DEBUG   "-ggdb" CACHE STRING "" FORCE)

# C++ flags
# Contents of *_RELEASE and *_DEBUG parameters are appended according to the
# selected configuration
# -fvisibility-inlines-hidden: forces inline methods to be excluded from ELF
# binaries, thus, making code smaller.
set(CMAKE_CXX_FLAGS "${CMAKE_C_FLAGS} -fvisibility-inlines-hidden"
                    CACHE STRING "" FORCE)
set(CMAKE_CXX_FLAGS_RELEASE "-s -fno-semantic-interposition"    CACHE STRING "" FORCE)
set(CMAKE_CXX_FLAGS_DEBUG   "-ggdb" CACHE STRING "" FORCE)

# Linker flags
# --as-needed: remove unneeded libraries in ELF DT_NEEDED sections
# -O1: enable linker optimization
# -rpath=...: set a default runtime path for linking executables
set(CMAKE_SHARED_LINKER_FLAGS "-Wl,--as-needed,-O1")
set(CMAKE_EXE_LINKER_FLAGS "${CMAKE_SHARED_LINKER_FLAGS} \"-Wl,-rpath,${CMAKE_STAGING_PREFIX}/usr/lib\"")

# security flag: use -fPIE to improve security
set(CMAKE_POSITION_INDEPENDENT_CODE TRUE)

# location of pkg-config .pc files in the staging directory
#set(ENV{PKG_CONFIG_PATH} "${CMAKE_STAGING_PREFIX}/lib/pkgconfig")

