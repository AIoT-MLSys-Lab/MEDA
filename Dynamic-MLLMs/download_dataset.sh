# wget -P /users/PAS2473/brucewan666/Data_and_model \
#     "https://huggingface.co/datasets/FreedomIntelligence/MileBench/resolve/main/MileBench_part0.tar.gz" \
#     "https://huggingface.co/datasets/FreedomIntelligence/MileBench/resolve/main/MileBench_part1.tar.gz" \
#     "https://huggingface.co/datasets/FreedomIntelligence/MileBench/resolve/main/MileBench_part2.tar.gz" \
#     "https://huggingface.co/datasets/FreedomIntelligence/MileBench/resolve/main/MileBench_part3.tar.gz" \
#     "https://huggingface.co/datasets/FreedomIntelligence/MileBench/resolve/main/MileBench_part4.tar.gz" \
#     "https://huggingface.co/datasets/FreedomIntelligence/MileBench/resolve/main/MileBench_part5.tar.gz"

# export HF_HOME="/users/PAS2473/brucewan666/Data_and_model"
# source ~/.bashrc
#!/bin/bash


DATA_DIR="/users/PAS2473/brucewan666/Data_and_model"


cd "$DATA_DIR" || { echo "Error: Directory $DATA_DIR not found!"; exit 1; }


for file in MileBench_part*.tar.gz
do
  echo "Extracting: $file"
  tar -xzvf "$file"
done