#!/bin/bash

mkdir -p /tmp/forest_data

curl -s -H "User-Agent: ForestApp-Report/1.0" "https://www.reddit.com/search.json?q=Forest+App+productivity&sort=new&limit=25&t=week" -o /tmp/forest_data/s1.json && sleep 2
curl -s -H "User-Agent: ForestApp-Report/1.0" "https://www.reddit.com/r/productivity/search.json?q=Forest+App&sort=new&limit=25&t=week&restrict_sr=1" -o /tmp/forest_data/s2.json && sleep 2
curl -s -H "User-Agent: ForestApp-Report/1.0" "https://www.reddit.com/r/nosurf/search.json?q=Forest&sort=new&limit=25&t=week&restrict_sr=1" -o /tmp/forest_data/s3.json && sleep 2
curl -s -H "User-Agent: ForestApp-Report/1.0" "https://www.reddit.com/r/ADHD/search.json?q=Forest+App&sort=new&limit=25&t=week&restrict_sr=1" -o /tmp/forest_data/s4.json && sleep 2
curl -s -H "User-Agent: ForestApp-Report/1.0" "https://www.reddit.com/r/getdisciplined/search.json?q=Forest+App&sort=new&limit=25&t=week&restrict_sr=1" -o /tmp/forest_data/s5.json && sleep 2
curl -s -H "User-Agent: ForestApp-Report/1.0" "https://www.reddit.com/search.json?q=Opal+app+screen+time&sort=new&limit=25&t=week" -o /tmp/forest_data/s6.json && sleep 2
curl -s -H "User-Agent: ForestApp-Report/1.0" "https://www.reddit.com/search.json?q=focus+friend+app&sort=new&limit=25&t=week" -o /tmp/forest_data/s7.json && sleep 2
curl -s -H "User-Agent: ForestApp-Report/1.0" "https://www.reddit.com/search.json?q=body+doubling+focus+app&sort=new&limit=25&t=week" -o /tmp/forest_data/s8.json

echo "Reddit searches complete"
