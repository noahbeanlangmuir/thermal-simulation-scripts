#! /bin/bash
# Automated film coefficient estimation (bisection on the surface temperature).
#
#   find_coef.sh <design.FCStd> <designs_dir>
#
# Environment: MAX_ITER (default 20). Logs for every step go to
# <designs_dir>/find_coef_logs/. Exit codes: 0 converged (result saved to
# config.json as "bisected_temp"), 2 temperature outside the config range,
# 3 simulation not at steady state, 4 no convergence within MAX_ITER,
# anything else: a step failed (see the log named in the message).
set -euo pipefail

fcstd_path=$1
designs=$2
MAX_ITER=${MAX_ITER:-20}
logs="$designs/find_coef_logs"
mkdir -p "$logs"
cp "$designs"/config.json "$designs"/temp_config.json
trap 'rm -f "$designs"/temp_config.json' EXIT

step() { # step <log name> <command...>: run, keep output in a log, stop on failure
    local name=$1; shift
    if ! "$@" > "$logs/$name.log" 2>&1; then
        echo "ERROR: '$*' failed, see $logs/$name.log" >&2
        tail -n 20 "$logs/$name.log" >&2
        exit 1
    fi
}

# Get absolute boundaries
export TMAX=$(jq -r '.temperature | .max' "$designs"/temp_config.json)
export TMIN=$(jq -r '.temperature | .min' "$designs"/temp_config.json)
iteration=0
while [ "$iteration" -lt "$MAX_ITER" ]; do
    iteration=$((iteration + 1))
    echo ""
    echo "------------------ #$iteration Iteration "
    export ITERATION="$iteration"
    step "$iteration-1-calc-film-coefs" tpre calc-film-coefs --fcstd "$fcstd_path" --config "$designs"/temp_config.json
    step "$iteration-2-parse-fcstd" tpre parse-fcstd --fcstd "$fcstd_path" --inp "$designs" --log "$designs"
    job=$(jq -r '."Input file"' "$designs"/simulation.json)
    job=${job%.inp}
    step "$iteration-3-ccx" bash -c "cd '$designs' && ccx -i '$job'"
    if grep -q "\*ERROR" "$logs/$iteration-3-ccx.log"; then
        echo "ERROR: CalculiX reported an error, see $logs/$iteration-3-ccx.log" >&2
        exit 1
    fi
    rm -f "$designs"/temperature.csv
    step "$iteration-4-convert" tpost convert --frd "$designs/$job.frd" --vtk "$designs"/vtk
    step "$iteration-5-csv" tpost csv --vtk "$designs"/vtk --sta "$designs/$job.sta" --output "$designs"/temperature.csv
    set +e
    tpre bisect-temperature --config "$designs"/temp_config.json --csv "$designs"/temperature.csv
    rc=$?
    set -e
    case $rc in
        0)
            t=$(jq -r '.bisected_temp' "$designs"/temp_config.json)
            jq --argjson t "$t" '.bisected_temp = $t' "$designs"/config.json > "$designs"/config.json.new
            mv "$designs"/config.json.new "$designs"/config.json
            echo "Converged at $t C after $iteration iterations; saved as bisected_temp in $designs/config.json"
            jq '."Heat Dissipation"' "$designs"/simulation.json
            exit 0 ;;
        10) ;;  # not converged yet, next iteration
        2|3) exit "$rc" ;;
        *) echo "ERROR: tpre bisect-temperature failed (exit $rc)" >&2; exit "$rc" ;;
    esac
done
echo "ERROR: no convergence after $MAX_ITER iterations (set MAX_ITER to allow more)" >&2
exit 4
