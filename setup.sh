#!/bin/bash
# Clara Pipeline — Setup & Run Script
# Usage: bash setup.sh

set -e

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║        Clara Answers Pipeline — Setup            ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is required. Install from https://python.org"
    exit 1
fi
echo "✓ Python 3 found: $(python3 --version)"

# Install dependencies
echo ""
echo "▶ Installing dependencies..."
pip install python-docx --break-system-packages -q 2>/dev/null || pip install python-docx -q
echo "✓ python-docx installed"

# Create data directory
mkdir -p data outputs/accounts

# Check for API key
echo ""
if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "ℹ  No ANTHROPIC_API_KEY set — using zero-cost rule-based extraction"
    echo "   To use Claude API: export ANTHROPIC_API_KEY=your_key"
else
    echo "✓ ANTHROPIC_API_KEY detected — will use Claude API for extraction"
fi

# Run on existing sample if available
echo ""
echo "▶ Checking for sample data..."
SAMPLE="data/onboarding_bens-electric-solutions.docx"
if [ -f "$SAMPLE" ]; then
    echo "  Found: $SAMPLE"
    echo ""
    echo "▶ Running Pipeline A (v1)..."
    python3 scripts/local_pipeline.py \
        --transcript "$SAMPLE" \
        --source-type onboarding_call

    echo ""
    ONBOARDING_UPDATE="data/onboarding_update_bens-electric-solutions.txt"
    if [ -f "$ONBOARDING_UPDATE" ]; then
        echo "▶ Running Pipeline B (v1 → v2)..."
        python3 scripts/pipeline_b.py \
            --update "$ONBOARDING_UPDATE" \
            --v1-memo outputs/accounts/ben-s-electric-solutions/v1/account_memo.json
    fi
else
    echo "  No sample data found. Add transcripts to data/ folder and run:"
    echo ""
    echo "  # Single file:"
    echo "  python3 scripts/local_pipeline.py --transcript data/your_file.docx"
    echo ""
    echo "  # Batch (all files in data/):"
    echo "  python3 scripts/batch_run.py --dataset ./data"
fi

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║  ✅ Setup complete!                              ║"
echo "║                                                  ║"
echo "║  Open dashboard/index.html in your browser      ║"
echo "║  Outputs in: outputs/accounts/                  ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""
