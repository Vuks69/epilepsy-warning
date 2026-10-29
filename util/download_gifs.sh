#!/usr/bin/env bash

# Batch download utility for links in a list file
# Usage: ./download_gifs.sh -i <interval_seconds> <list_file> or ./download_gifs.sh <list_file>

INTERVAL=5

# Parse args
while getopts "i:" opt; do
  case $opt in
    i)
      INTERVAL="$OPTARG"
      ;;
    *)
      echo "Usage: $0 [-i interval_seconds] <list_file>" >&2
      exit 1
      ;;
  esac
done
shift $((OPTIND-1))

LIST_FILE="$1"

if [ -z "$LIST_FILE" ]; then
  echo "Usage: $0 [-i interval_seconds] <list_file>" >&2
  exit 1
fi

if [ ! -f "$LIST_FILE" ]; then
  echo "Error: File '$LIST_FILE' not found" >&2
  exit 1
fi

# Get basename without extension
BASENAME=$(basename "$LIST_FILE")
DIRNAME="${BASENAME%.*}"

# Create output directory
mkdir -p "$DIRNAME"

# Count total lines
count=0
while IFS= read -r url || [ -n "$url" ]; do
  # Skip empty lines
  [ -z "$(echo "$url" | tr -d '[:space:]')" ] && continue
  ((count++))
done < "$LIST_FILE"

num=1
current=0
while IFS= read -r url || [ -n "$url" ]; do
  # Skip empty lines
  url_clean=$(echo "$url" | tr -d '[:space:]')
  [ -z "$url_clean" ] && continue
  ((current++))
  
  # Determine extension from URL
  # Try to get extension from path
  path=$(echo "$url_clean" | sed -n 's|.*/||p' | sed -n 's|\?.*||p')
  ext=$(echo "$path" | sed -n 's|.*\.||p')
  # If no extension found, default to gif
  if [ -z "$ext" ] || [ "$ext" = "$path" ]; then
    ext="gif"
  fi
  # Lowercase extension
  ext=$(echo "$ext" | tr '[:upper:]' '[:lower:]')
  
  outfile="${DIRNAME}/${num}.${ext}"
  echo "[$current/$count] Downloading to $outfile..."
  wget -O "$outfile" "$url_clean" 2>&1 | tail -1
  
  ((num++))
  
  # Throttle if not last download
  if [ $current -lt $count ]; then
    sleep "$INTERVAL"
  fi
done < "$LIST_FILE"

echo "Done. Downloaded $((num-1)) files to $DIRNAME/"
