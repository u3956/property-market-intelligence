# Sample: the morning digest (7 Oct 2026, shortened)

The bot posts this message to the Telegram group every morning, in French. Prices come from the site in XPF and are shown in EUR at the fixed rate. Each listing has three commands: keep it, drop it, or draft an email to the agency.

```
🏡 Digest — Tahiti · 07/10/2026
🎯 Vente ≤ [price ceiling] · tracking 119 annonces

🏷️ VENTE ≤ [price ceiling] — nouvelles publiées
   · 24h: 9  · moy 284 752 € · 5 940 €/m²
   · 7j: 28  · moy 274 738 € · 6 023 €/m²
   · 30j: 54  · moy 282 418 € · 5 831 €/m²

🔑 LOCATION — nouvelles publiées
   · 24h: 44  · moy 1 825 € · 24 €/m²/mois
   · 7j: 137  · moy 1 733 € · 22 €/m²/mois
   · 30j: 219  · moy 1 795 € · 23 €/m²/mois

✨ Nouvelles annonces (vente ≤ [price ceiling]) — 9

🏠 Maison – Tiarei · 75 m²
   💰 332 016 € · 4 427 €/m² · Poroi Immobilier
   ✅ /keep40961   ✖ /no40961
   ✍️ /contact_40961

🏢 Appartement – Papeete · 29 m²
   💰 236 316 € · 8 208 €/m² · Atike Immobilier
   ✅ /keep39331   ✖ /no39331
   ✍️ /contact_39331

…
```

What each command does:

- `/keep40961`: adds the listing to the shared shortlist and hides it from later digests. A bare `/keep` shows the shortlist, with every price checked live on the site.
- `/no40961`: drops the listing. It disappears from later digests.
- `/contact_40961`: posts a ready-to-send email draft to the listing's agency. The group can edit it in plain words, then send it.
