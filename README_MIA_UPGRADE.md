# Mia AI Influencer Upgrade

This bundle upgrades the existing Agnes/Kokoro/Discord project in place. It does not create a second bot or a second file server.

## Main command

`/mia Mia explores an abandoned hotel and discovers an old photograph of herself.`

## Output

Each job keeps its working assets under `jobs/JOB_ID/` and publishes durable files under `/var/www/agnes-videos/JOB_ID/`:

- `mia_video.mp4`
- `mia_youtube.txt`
- `mia_script.txt`
- `story_plan.json`
- `mia_captions.ass`
- `metadata.json`

The persistent identity reference is kept at `characters/mia/reference_image.png` and published for Agnes reference conditioning at `/var/www/agnes-videos/characters/mia/reference_image.png`.

## Deployment

Use the included `install_mia_upgrade.sh` from `/root/sakana` or manually copy the included directories over the existing repository. Keep `config/.env` unchanged except for the values documented in `ENV_REQUIRED.txt`.
