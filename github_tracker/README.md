# Kalshi BTC 15-minute paper tracker

This script tracks hypothetical 45¢ YES and NO orders. It does not connect to a Kalshi account or place real trades. It uses Python's standard library, so no packages need to be installed.

## Run on GitHub Codespaces

1. Create a GitHub repository and upload these three files to its root: `kalshi_btc15m_dual45_paper.py`, `README.md`, and `.gitignore`.
2. In the repository, select **Code → Codespaces → Create codespace on main**.
3. In the Codespaces terminal, run:

   ```bash
   python kalshi_btc15m_dual45_paper.py
   ```

4. Look for `RUNNING | PAPER ONLY` in the terminal. Press Ctrl+C to stop.

The script saves its paper history in `kalshi_btc15m_dual45_state.json`. That file is excluded from Git commits. Codespaces stop after inactivity, so this setup is for running and checking the code interactively, not continuous operation.
