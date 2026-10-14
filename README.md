# Card Flip Desk

Django-app die het verkooptraject van sportkaarten bijhoudt, van inkoop tot
verkoop op eBay, en uitrekent wat er na alle kosten echt overblijft.

## Status

| MVP-stap | Onderdeel | Status |
|---|---|---|
| 1 | Project, accounts, kaartmodel, voorraad-CRUD | ✅ |
| 2 | CSV-import met kolomkoppeling en foutrapport | ✅ |
| 3 | Kostencalculator met FeeProfile (vooruit en omgekeerd) | ✅ |
| 4 | Verkopen registreren, winst per kaart en per maand | ✅ |
| 5 | Foto's per kaart (validatie, thumbnails, EXIF weg, privé-opslag) | ✅ |
| 6 | Dashboard met KPI's, grafieken en voorraadleeftijd | ✅ |
| 7 | Listing-generator met templates en controles | ✅ |
| 8 | Waarschuwingen voor oude voorraad, 'Aandacht nodig', wekelijkse mail | ✅ |
| 9 | eBay OAuth + Browse API voor prijsadvies | ✅ |
| 10 | REST API met token-auth en OpenAPI-docs | ✅ |
| 11 | README met screenshots en architectuur | open |

## Starten

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python manage.py migrate
.venv\Scripts\python manage.py seed_demo   # lokaal demo-account, zie inventory/management/commands/seed_demo.py
.venv\Scripts\python manage.py runserver
```

Tests: `.venv\Scripts\python -m pytest`

## Architectuur

```
config/      settings, urls, registratie (maakt een startkostenprofiel aan)
inventory/   Card, Purchase, CardQuerySet (filters, voorraadwaarde), CSV-import,
             CardPhoto + photos.py (verwerking), storage.py (privé-opslag),
             aging.py (leeftijd + voorstellen), digest.py (wekelijkse mail)
finance/     calculator.py (pure functies), FeeProfile
sales/       Listing, Sale, SaleQuerySet (winst via subquery), services.register_sale,
             dashboard.py (voegt queryset-cijfers samen, expliciete 'today'),
             listing_generator.py (titels/beschrijvingen uit patronen), ListingTemplate
ebay/        client.py (tokens, retries, budget, ETag-cache), oauth.py, crypto.py
pricing/     advice.py (actieve listings + eigen historie), PriceSnapshot
api/         DRF-serializers en viewsets, token-pagina
tests/       pytest-django, respx voor eBay-mocks
```

**Bedrijfsregels in services, niet in views.** `finance/calculator.py` heeft
geen database-afhankelijkheid; views roepen het alleen aan.

### Rekenregels (calculator)

- Alles in `Decimal`; een float geeft een `TypeError`.
- Commissie en betaalkosten over prijs + verzendopbrengst.
- Elke kostenpost apart afgerond op centen, `ROUND_HALF_UP`.
- Marge = winst / bruto × 100, op 0,1 afgerond; `None` bij bruto 0.
- Omgekeerd rekenen geeft de **laagste** prijs die de doelwinst haalt. Door
  afronding kan dat een cent onder de "naïeve" prijs liggen.

### Tarieven

Tarieven staan in `FeeProfile` (per categorie, met `valid_from`), niet in de
code. Een verkoop gebruikt het profiel dat op de verkoopdatum gold en slaat
de berekende bedragen op, zodat een latere tariefwijziging oude winsten niet
verandert. Het startprofiel (13,25 % + € 0,35) is een voorbeeld; controleer
de actuele tarieven in je eBay-account.

### Toegang

Elke view filtert op `owner=request.user` en geeft 404 (niet 403) bij
andermans data. Dit wordt per endpoint getest.

### Foto's

- **Inhoud bepaalt het type.** Pillow leest de kop; alleen JPEG, PNG en WebP
  komen door. Extensie en Content-Type van de browser tellen niet.
- **Limieten vóór decoderen.** Bestandsgrootte (10 MB) en afmetingen
  (8000 px) worden gecontroleerd voordat de pixels in het geheugen komen.
- **Alles wordt hercodeerd.** Verkleind tot 1600 px plus een thumbnail van
  300 px. Daarbij verdwijnen EXIF (GPS, camera), XMP en PNG-tekstblokken; de
  EXIF-oriëntatie wordt eerst toegepast. Het kleurprofiel blijft.
- **Willekeurige namen.** `cards/<uuid>.<ext>`; de bestandsnaam van de
  gebruiker komt nergens in het pad.
- **Geen publieke URL.** Bestanden staan in `PRIVATE_MEDIA_ROOT` en worden
  uitgeleverd door een view die de eigenaar controleert
  (`Cache-Control: private`). `storage.url()` gooit bewust een fout.
  Overstappen op S3 = de `photos`-backend in `STORAGES` vervangen.
- **Maximaal één hoofdfoto**, afgedwongen met een database-constraint.
- **Opruimen na commit.** Bij verwijderen of vervangen (ook via het
  verwijderen van een kaart) gaan de bestanden pas weg als de transactie
  slaagt.
### Dashboard

- **Query's in querysets** (`SaleQuerySet.totals/per_set/with_days_to_sale`,
  `CardQuerySet.unsold_by_age`); `sales/dashboard.py` voegt ze samen en krijgt
  `today` mee, zodat periodegrenzen zonder klokmanipulatie te testen zijn.
  De hele pagina draait in een vast, getest maximum aantal query's.
- **Marge is gewogen:** totale winst ÷ totale omzet, niet het gemiddelde van
  losse marges (dan telt een kaart van € 1 even zwaar als een van € 50).
- **Dagen tot verkoop** tellen vanaf "te koop sinds", anders vanaf de eerste
  inkoopdatum.
- **Periodefilter** (30 / 90 dagen, 12 maanden, alles) geldt voor alle
  verkoopcijfers; voorraadcijfers gelden altijd voor vandaag. Maanden zonder
  verkoop staan als nul in de grafiek.
- **Grafieken** (Chart.js): één y-as per grafiek, kleuren uit CSS-variabelen
  met aparte, gevalideerde stappen voor licht en donker, tooltips, en een
  tabelweergave onder elke grafiek.
### Listing-generator

- **Patronen** met plaatshouders (`{jaar} {set} {speler} #{nummer} {variant} {conditie}`),
  per gebruiker op te slaan als template. Onbekende plaatshouders worden bij
  het opslaan geweigerd.
- **Lege velden laten niets achter:** geen losse `#`, `()` of dubbele spaties,
  en een regel als `Variant:` zonder waarde valt weg. Base-variant blijft leeg.
- **Titel max. 80 tekens** (eBay). Langer wordt afgekapt op een woordgrens,
  met een waarschuwing die noemt wat er wegvalt. Opslaan boven 80 kan niet.
- **Tekens:** Unicode wordt genormaliseerd (NFC), stuurtekens en regeleinden
  verdwijnen uit de titel; accenten blijven. Kaartgegevens worden niet
  opnieuw als patroon gelezen (`{set}` als spelersnaam blijft letterlijk).
  Alles is platte tekst en wordt bij het tonen ge-escaped.
- **Controles:** titellengte, lege velden en de fotochecklist uit stap 5.
- **Vraagprijs** toont direct de winst via de kostencalculator.
- **Concept / actief:** "actief" zet de kaart op te koop met een
  'te koop sinds'-datum; een latere verkoop gebruikt deze listing.
### Oude voorraad

- **Leeftijd** telt vanaf "te koop sinds"; voor kaarten die nog niet te koop
  staan vanaf de eerste inkoop (zonder inkoop: vanaf invoer). Berekend in
  `CardQuerySet.with_age_start()`, dus filteren en sorteren gebeurt in de
  database.
- **Drempels per gebruiker** (standaard 30 / 60 / 90 dagen). Precies op de
  drempel telt al mee. Kleurcode én tekstlabel in het voorraadoverzicht.
- **Voorstellen:** 30+ foto's of titel verbeteren; 60+ prijs verlagen met een
  instelbaar percentage, met direct de nieuwe winst en marge via de
  calculator en een waarschuwing bij verlies; 90+ bundelen met kaarten uit
  dezelfde set, of afschrijven als die er niet zijn.
- **Vastzetten** tot een datum: zo'n kaart geeft geen meldingen. Acties
  (vastzetten, losmaken, prijs verlaagd) komen in `InventoryNote`.
- **`aging.py` krijgt `today` mee**; de aandachtslijst kost een vast aantal
  query's, onafhankelijk van het aantal kaarten.

### Wekelijkse mail

`python manage.py send_stale_digest` stuurt elke gebruiker met een
e-mailadres en de mail aan een overzicht, maar **niets als er niets te melden
is**, en hooguit één keer per 7 dagen (`--force` negeert dat, `--dry-run`
verstuurt niets, `--today JJJJ-MM-DD` voor tests). Het command staat los van
de planner; plan het zelf in:

```bash
# cron (Linux/macOS), elke maandag 08:00
0 8 * * 1 cd /pad/naar/card-flip-desk && .venv/bin/python manage.py send_stale_digest
```

```bash
schtasks /Create /SC WEEKLY /D MON /ST 08:00 /TN "Card Flip Desk digest" /TR "\"D:\GitHub\Card Flip Desk\.venv\Scripts\python.exe\" \"D:\GitHub\Card Flip Desk\manage.py\" send_stale_digest"
```

Stel voor echte mail een SMTP-backend in `MAILERS` in en zet `SITE_URL` en
`DEFAULT_FROM_EMAIL` via omgevingsvariabelen.
### eBay-koppeling

**Wat eBay toestaat (onderzocht oktober 2026, developer.ebay.com):**

- `GET /buy/browse/v1/item_summary/search` heeft alleen een
  **applicatietoken** nodig (client credentials, scope
  `https://api.ebay.com/oauth/api_scope`). Standaard 5.000 calls per dag;
  tokens 1.000 per dag, 2 uur geldig. Zonder `buyingOptions`-filter komen
  alleen Buy It Now-listings terug.
- De Buy API's zijn deels *Limited Release*: in de **sandbox** mag iedereen
  met een developeraccount, voor **productie** moet je toegang aanvragen
  (eBay Partner Network) en goedkeuring is niet gegarandeerd.
- **Verkochte items** (Marketplace Insights API) zijn alleen beperkt
  toegankelijk. Daarom telt de eigen verkoophistorie in de app zwaarder en
  komt er een CSV-import uit Seller Hub.
- Listings plaatsen loopt via de Sell API's en een **gebruikerstoken**
  (Authorization Code Flow met een RuName). Die flow is gebouwd en getest,
  maar wordt nog nergens voor gebruikt: de app leest en rekent eerst.

**Hoe de client werkt:** applicatietoken in de cache tot 5 minuten vóór
verloop; bij een 401 één keer een nieuw token. Retries met exponentiële
backoff bij netwerkfouten, 429 en 5xx (een `Retry-After` gaat voor, maximaal
10 s). Een dagbudget (`EBAY_DAILY_CALL_BUDGET`, standaard 4.500) onder de
eBay-limiet. GET-antwoorden komen in `CachedResponse` (standaard 6 uur
vers, daarna opnieuw valideren met `If-None-Match`). Is eBay onbereikbaar,
dan toont de app het laatst bewaarde antwoord met een melding, of anders
alleen de eigen historie. De rest van de app werkt gewoon door.

**Prijsadvies:** zoekterm uit de kaartgegevens (aan te passen), alleen
listings in `EBAY_CURRENCY` en met de achternaam van de speler in de titel.
Je ziet minimum, mediaan, maximum en het aantal. De richtprijs is de mediaan
van je eigen verkopen (vanaf 2), anders de mediaan van de vraagprijzen, met
de waarschuwing dat dat geen verkoopprijzen zijn. Elke ophaalactie geeft een
`PriceSnapshot`. eBay-data wordt behandeld als onbetrouwbare invoer:
bedragen als Decimal, links alleen naar https-eBay-domeinen, en alles
ge-escaped.

**Tokens in de database** staan versleuteld met Fernet
(`TOKEN_ENCRYPTION_KEYS`, meerdere sleutels voor rotatie). Buiten DEBUG
weigert de app te starten met tokens zonder sleutel. OAuth `state` wordt
in de sessie bewaard en in constante tijd vergeleken.

**Instellen** (omgevingsvariabelen, nooit in git):

| Variabele | Voorbeeld |
|---|---|
| `EBAY_ENVIRONMENT` | `sandbox` of `production` |
| `EBAY_CLIENT_ID` / `EBAY_CLIENT_SECRET` | uit *Application Keys* |
| `EBAY_RUNAME` | alleen voor de gebruikerskoppeling; accept-URL = `SITE_URL` + `/ebay/callback/` |
| `EBAY_MARKETPLACE_ID` / `EBAY_CURRENCY` | `EBAY_NL` / `EUR` |
| `EBAY_CATEGORY_IDS` | optioneel, om het zoeken te beperken |
| `TOKEN_ENCRYPTION_KEYS` | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
### REST API

Basis-URL `/api/v1/`, interactieve documentatie op **`/api/v1/docs/`**
(Swagger UI) en het schema op `/api/v1/schema/` (OpenAPI 3, drf-spectacular,
valideert zonder waarschuwingen).

| Endpoint | Methoden |
|---|---|
| `cards/` (+ `?q=&status=&set_name=&year=`) | CRUD, `POST cards/{id}/generate-listing/` |
| `purchases/` | CRUD |
| `photos/` | upload (multipart), lijst, `PATCH` label, `DELETE`, `POST {id}/set-main/`, `GET {id}/file/`, `GET {id}/thumbnail/` |
| `listings/`, `listing-templates/` | CRUD (een verkochte listing is bevroren) |
| `sales/` | lijst, detail, aanmaken (kosten via het kostenprofiel) |
| `fee-profiles/` | CRUD |
| `calculator/`, `calculator/reverse/` | `POST` |
| `auth/token/` | `POST` gebruikersnaam + wachtwoord → token (max. 10 per minuut) |

```bash
curl -H "Authorization: Token <token>" http://localhost:8000/api/v1/cards/?status=for_sale
```

- **Authenticatie:** `Authorization: Token …`. Het token maak, vernieuw of
  trek je in op de pagina **API** in de app. Voor de docs in de browser werkt
  ook de gewone sessie.
- **Alleen eigen data**, op twee lagen: elke queryset is gefilterd op de
  gebruiker (andermans object geeft 404), en een `IsOwner`-permissie
  controleert het object nog eens. Verwijst invoer naar andermans kaart of
  kostenprofiel, dan volgt dezelfde 400 als bij een id dat niet bestaat.
- **Dezelfde services als de webapp:** foto-validatie en EXIF-verwijdering,
  `register_sale`, de calculator en de listing-generator. De regels gelden
  dus ook via de API.
- **Bedragen zijn decimale strings** (`"5.24"`), geen floats.
- **Throttling:** 2000 verzoeken per uur per gebruiker. Lijsten zijn
  gepagineerd per 50 en draaien in een vast aantal query's.