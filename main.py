"""Punto de entrada: python main.py [proyecto.eia]"""
import sys

from editoria.app import run

if __name__ == "__main__":
    sys.exit(run(sys.argv))
