# Account Pulse

Build a Key Account Manager (KAM) meeting assistant web app for a workwear rental service, implementing the Default mode's 3-step meeting workflow using the attached reference ZIP (lindstrom-review-v6.zip) for data schemas, sample data, metrics, and business logic.

Requirements and customer feedback:
1. Target Persona & Experience:
   - Customer-facing Key Account Managers are busy and non-technical. They need a low-friction, graphic-focused, interactive experience.
   - Include a mode toggle between Default (the streamlined 3-step meeting assistant) and Advanced mode (deep-dive analytics).

2. Default Mode 3-Step Meeting Workflow:
   - Step 1: Account Pulse — High-level health check with core metrics (garments in circulation, washing frequency, repair rates, cost, and environmental impact). Garment utilisation metric comparing washes with allocated garments, using a healthy band of 30–70% (higher for food/hygiene accounts) with KAM override controls. Plain-language outlier explanations (e.g., "% vs average or prior period", why specific sites or departments stand out). Original data remains intact, showing exceptions and allowing row exclusion without re-upload.
   - Step 2: Meeting Customizer — Tailor the review to meeting attendees (e.g., Procurement / Finance, Sustainability Lead, Operations / Site Manager) and customer priorities (cost reduction, CO2 emissions, water conservation, textile recycling / circularity, hygiene standards). Persist the chosen account throughout the workflow.
   - Step 3: Client-Ready Deck & Talking Points — Interactive presentation slide previews, executive summary, bulleted talking points for each slide matched to attendees, and export options. Include textile recycling impact where supported by data.

This project was built with [Lovable](https://lovable.dev).

## Build with Lovable

Continue developing this project in the [Lovable editor](https://lovable.dev/projects/17ce00fe-1bac-414d-b6c8-5d57a4470e23).

- **Ship faster**: describe what you want to build and Lovable handles the code.
- **Stay in sync**: every change made in Lovable is committed straight to this repository.
- **Full ownership**: this code is yours. Push to `main` on GitHub and your changes sync back into Lovable, ready for your next prompt.

## Development

Prefer working locally? You need Node.js and npm — [install with nvm](https://github.com/nvm-sh/nvm#installing-and-updating).

```sh
git clone <this-repository-url>
cd <repository-name>
npm i
npm run dev
```
