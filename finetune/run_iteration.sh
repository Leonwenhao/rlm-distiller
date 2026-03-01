#!/bin/bash
# Run one complete fine-tuning + serving iteration for RLM Distiller.
#
# Usage: ./finetune/run_iteration.sh <iteration_number> <training_data_path> [eval_data_path] [port]
# Example: ./finetune/run_iteration.sh 1 data/orchestration_traces_train.jsonl
#
# This script:
# 1. Runs QLoRA fine-tuning
# 2. Kills any existing vLLM server
# 3. Starts serving the new model
# 4. Waits for the server to be healthy
# 5. Prints the endpoint URL

set -euo pipefail

ITERATION=${1:?"Usage: $0 <iteration> <training_data> [eval_data] [port]"}
TRAINING_DATA=${2:?"Usage: $0 <iteration> <training_data> [eval_data] [port]"}
EVAL_DATA=${3:-data/orchestration_traces_eval.jsonl}
PORT=${4:-8000}
CHECKPOINT_DIR="checkpoints/iteration_${ITERATION}"

echo "============================================================"
echo "  RLM Distiller: Fine-tuning iteration ${ITERATION}"
echo "============================================================"
echo "Training data: ${TRAINING_DATA}"
echo "Eval data:     ${EVAL_DATA}"
echo "Output:        ${CHECKPOINT_DIR}"
echo "Serve port:    ${PORT}"
echo "============================================================"

# Validate inputs
if [ ! -f "$TRAINING_DATA" ]; then
    echo "ERROR: Training data not found: ${TRAINING_DATA}"
    exit 1
fi

# Step 1: Train
echo ""
echo ">>> Step 1/4: Running QLoRA fine-tuning..."
echo ""

TRAIN_CMD="python finetune/train_qlora.py \
    --training_data ${TRAINING_DATA} \
    --output_dir ${CHECKPOINT_DIR} \
    --num_epochs 3 \
    --learning_rate 2e-4 \
    --batch_size 2 \
    --gradient_accumulation_steps 4 \
    --max_seq_length 4096 \
    --wandb_project rlm-distiller \
    --iteration ${ITERATION}"

if [ -f "$EVAL_DATA" ]; then
    TRAIN_CMD="${TRAIN_CMD} --eval_data ${EVAL_DATA}"
fi

eval $TRAIN_CMD

if [ $? -ne 0 ]; then
    echo "ERROR: Training failed!"
    exit 1
fi

echo ""
echo ">>> Step 2/4: Stopping existing model server..."
echo ""

# Step 2: Kill existing server
pkill -f "vllm.entrypoints.openai.api_server" 2>/dev/null || true
pkill -f "serve_model.py" 2>/dev/null || true
sleep 3

# Step 3: Serve new model
echo ">>> Step 3/4: Starting model server..."
echo ""

python finetune/serve_model.py \
    --base_model mistralai/Mistral-Small-3.1-24B-Instruct-2503 \
    --lora_path "$CHECKPOINT_DIR" \
    --port "$PORT" &

SERVER_PID=$!
echo "Server PID: ${SERVER_PID}"

# Step 4: Wait for health check
echo ""
echo ">>> Step 4/4: Waiting for model server to be ready..."
echo ""

TIMEOUT=60
for i in $(seq 1 $TIMEOUT); do
    if ! kill -0 $SERVER_PID 2>/dev/null; then
        echo "ERROR: Server process died unexpectedly"
        echo "Retrying with merge-and-serve fallback..."

        python finetune/serve_model.py \
            --base_model mistralai/Mistral-Small-3.1-24B-Instruct-2503 \
            --lora_path "$CHECKPOINT_DIR" \
            --port "$PORT" \
            --merge_and_serve &

        SERVER_PID=$!
        sleep 10
        continue
    fi

    if curl -s "http://localhost:${PORT}/v1/models" > /dev/null 2>&1; then
        echo ""
        echo "============================================================"
        echo "  Model server is ready!"
        echo "  Endpoint: http://localhost:${PORT}/v1/chat/completions"
        echo "  Model name: rlm-distiller"
        echo "  Server PID: ${SERVER_PID}"
        echo "============================================================"
        echo ""
        echo "Test with:"
        echo "  curl http://localhost:${PORT}/v1/chat/completions \\"
        echo "    -H 'Content-Type: application/json' \\"
        echo "    -d '{\"model\": \"rlm-distiller\", \"messages\": [{\"role\": \"user\", \"content\": \"Hello\"}]}'"
        exit 0
    fi

    echo "  Waiting... (${i}/${TIMEOUT}, checking every 5s)"
    sleep 5
done

echo "ERROR: Model server failed to start within $((TIMEOUT * 5 / 60)) minutes"
kill $SERVER_PID 2>/dev/null || true
exit 1
