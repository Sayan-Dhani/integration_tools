#!/bin/bash
# Usage: ./balistic_calibration.sh modulename co2temperature
if [ $# -le 2 ]; then
    echo "Usage: $0 modulename co2temperature [tag]"
    exit 1
fi

OUT=`/home/thermal/integration_tools/modulesearch.py $1`
NOMINAL_TEMPERATURE=$2

# ********** module: PS_26_IPG-10014 ***********
# LV: LV8.5
# HV: HV2.9
# FC7: FC7OT6_OG3
# Mounted_on: L1_47_A#1;2
# Speed: 5G
# Extract OG number, OT number, and LV channel from OUT
OG_NUMBER=$(echo "$OUT" | grep -o 'OG[0-9]\+' | perl -pe 's/.*OG//')
OT_NUMBER=$(echo "$OUT" | grep -o 'OT[0-9]\+'| perl -pe 's/OT//')
LV_CHANNEL=$(echo "$OUT" | grep -o 'LV[0-9.]\+' | perl -pe 's/.*LV: //')

echo "Extracted OG Number: $OG_NUMBER"
echo "Extracted OT Number: $OT_NUMBER"
echo "Extracted LV Channel: $LV_CHANNEL"

source setup.sh
cp balistic_template.xml ./balistic.xml
perl -pe 's/target=.*:5000/target=192.168.0.19'$OT_NUMBER':5000/' -i balistic.xml
perl -pe 's/OpticalGroup Id="0"/OpticalGroup Id="'$OG_NUMBER'"/' -i balistic.xml

runCalibration -f balistic.xml  -c monitoronly  -b >& /tmp/balistic.log &
#get pid of the last background process
pid=$!
echo "Running calibration with PID: $pid"
sleep 1
/home/thermal/integration_tools/caen/caencli.py -c $LV_CHANNEL --on
echo "CAEN channel $LV_CHANNEL turned on."

# Capture MQTT messages and parse JSON output
echo "Capturing MQTT data..."
mqtt_output=$(timeout 90 mosquitto_sub -h 192.168.0.45 -t '/ph2acf/#' -C 1)

# Parse and display JSON output
#curl -X PUT   -H "Content-Type: application/json"   -d '{"temperature_offsets": {"C0": 10, "C1": 20}}'   http://cmslabserver:5000/modules/PS_40_05_IBA-00001

echo "Parsing MQTT JSON data..."
echo "$mqtt_output" | while IFS= read -r line; do
    if [ -n "$line" ]; then
        echo "Raw JSON: $line"
        echo "Parsed values:"
        
        # Parse JSON fields using grep and sed
        counter=$(echo "$line" | grep -o '"counter":[^,}]*' | sed 's/"counter"://')
        timestamp=$(echo "$line" | grep -o '"timestamp":[^,}]*' | sed 's/"timestamp"://')
        beboardid=$(echo "$line" | grep -o '"BeBoardId":[^,}]*' | sed 's/"BeBoardId"://')
        fuseid=$(echo "$line" | grep -o '"LpGBT_OG'$OG_NUMBER'_fuseId":[^,}]*' | sed 's/"LpGBT_OG'$OG_NUMBER'_fuseId"://')
        
        echo "  counter: $counter"
        echo "  timestamp: $timestamp"
        echo "  BeBoardId: $beboardid"
        echo "  LpGBT_OG${OG_NUMBER}_fuseId: $fuseid"
        
        # Parse all temperature fields
        echo "  Temperature readings:"
        
        # Build JSON payload for temperature offsets
        module_name=$(echo "$1" | tr '[:lower:]' '[:upper:]')
        json_payload='{"temperature_offsets'$3'":{'
        first_entry=true
        
        for field in $(echo "$line" | grep -o '"[^"]*_temp":[^,}]*'); do
            field_name=$(echo "$field" | cut -d':' -f1 | sed 's/"//g')
            field_value=$(echo "$field" | cut -d':' -f2)
            #echo "    $field_name: $field_value"
            #e.g. MPA_H7_C8_temp or SSA_H7_C1_temp
            if [[ "$field_name" =~ (SSA|MPA)_H[0-9]+_C[0-9]+_temp ]]; then
                # Extract chip type (SSA or MPA)
                chip_type=$(echo "$field_name" | grep -oE '^(SSA|MPA)')
               # printf "  Chip type: $chip_type\n"
               # echo $field_name
                # Extract the numbers after H and after the second underscore
                h_num=$(echo "$field_name" | sed -E 's/.*_H([0-9]+)_.*/\1/')
                c_num=$(echo "$field_name" | sed -E 's/.*_H[0-9]+_C([0-9]+)_temp/\1/')
                
                # Convert H number using modulo 2
                h_converted=$((h_num % 2))
                converted_name="${chip_type}_H${h_converted}_${c_num}"
                
                # Calculate offset (READ - NOMINAL)
                offset=$(echo "$NOMINAL_TEMPERATURE - $field_value  " | bc -l)
                # Ensure offset has leading zero if needed
                offset=$(printf "%1.2f" "$offset")

                # Add comma if not first entry
                if [ "$first_entry" = false ]; then
                    json_payload+=','
                fi
                json_payload+="\"$converted_name\":$offset"
                first_entry=false
                
               # echo "    -> Converted to $converted_name with offset: $offset"
            else
                echo "    -> Skipping field $field_name as it does not match expected pattern."
            fi
        done
        
        json_payload+='}}'
        #escape the json payload quotes
        #json_payload=$(echo "$json_payload" | sed 's/"/\\"/g')
        # Push to database if we have temperature data
        if [ "$first_entry" = false ]; then
            echo "  Pushing temperature offsets to database..."
            curl_response=$(curl -s -X PUT \
                 -H "Content-Type: application/json" \
                 -d "$json_payload" \
                 "http://cmslabserver:5000/modules/$module_name")
            
            echo "  Database response: $curl_response"
            echo "  Payload sent: $json_payload"
        fi
        echo "----------------------------------------"
    fi
done 

kill $pid
echo "Calibration completed and process $pid killed."

# Final summary
echo "========================================="
echo "CALIBRATION SUMMARY"
echo "========================================="
echo "OT Number: $OT_NUMBER"
echo "OG Number: $OG_NUMBER"
echo "CAEN Channel: $LV_CHANNEL"
echo "All temperature and sensor data parsed above."
echo "========================================="

sleep 3
/home/thermal/integration_tools/caen/caencli.py -c $LV_CHANNEL --off
echo "CAEN channel $LV_CHANNEL turned off."