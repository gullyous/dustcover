# The standalone scripts are executed as subprocesses by test_standalone.py
# (each needs its own QApplication + clean module state); don't collect them.
collect_ignore = ["standalone"]
