#!/usr/bin/env bash
# Regenerate the SIMULATED example recordings, plots and reports in this folder.
set -e
cd "$(dirname "$0")/.."
python -m eeg_morse simulate "HELLO WORLD" --preset clench --seed 1 --out examples/sim_clench_hello.npz
python -m eeg_morse decode examples/sim_clench_hello.npz --preset clench --plot examples/clench_hello.png --json examples/clench_hello.json
python -m eeg_morse simulate "PARIS" --preset motor --unit 1.5 --seed 7 --out examples/sim_motor_calibration_paris.npz
python -m eeg_morse calibrate examples/sim_motor_calibration_paris.npz --preset motor --expect PARIS --out examples/motor_calibration.json
python -m eeg_morse simulate "SOS HELP" --preset motor --unit 1.5 --seed 3 --out examples/sim_motor_sos_help.npz
python -m eeg_morse decode examples/sim_motor_sos_help.npz --config examples/motor_calibration.json --plot examples/motor_sos_help.png --json examples/motor_sos_help.json
python -m eeg_morse live --replay examples/sim_clench_hello.npz --preset clench --speed 0 --rest 5
