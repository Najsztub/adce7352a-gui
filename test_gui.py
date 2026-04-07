#!/usr/bin/env python
"""Test script to validate meas_gl.py structure and imports."""

import sys
import ast

def check_syntax(filename):
    """Check if Python file has valid syntax."""
    try:
        with open(filename, 'r') as f:
            source = f.read()
        ast.parse(source)
        print(f"✓ Syntax valid: {filename}")
        return True
    except SyntaxError as e:
        print(f"✗ Syntax error in {filename}: {e}")
        return False

def check_imports():
    """Check if required imports are available."""
    required = ['numpy', 'PyQt5', 'OpenGL']
    for module in required:
        try:
            __import__(module)
            print(f"✓ {module} available")
        except ImportError as e:
            print(f"✗ {module} not available: {e}")

if __name__ == "__main__":
    print("Checking meas_gl.py...")
    if check_syntax('meas_gl.py'):
        print("\nChecking dependencies...")
        check_imports()
        print("\n✓ File structure looks good!")
    else:
        sys.exit(1)
