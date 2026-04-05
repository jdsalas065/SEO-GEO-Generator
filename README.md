# SEO-GEO-Generator

## Environment setup

This project reads API keys from a `.env` file at the repository root.

1. Open `.env` and set:

	`ANTHROPIC_API_KEY=<your_real_key>`

2. Start services again:

	`docker compose up -d postgres redis api worker`

If you need a template, use `.env.example`.