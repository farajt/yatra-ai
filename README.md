# Yatra AI

An AI travel planner for Indian travellers. Describe a trip in one sentence and get real flights, a hotel,
a budget in rupees, the weather and a day-by-day plan.

**Try it:** https://yatra-ai-euuzbhyqdtbxr6q9ddappc.streamlit.app/

## How it works

Several AI agents work together, built with LangGraph:

- Four agents search flights, hotels, the destination and the weather at the same time.
- The budget is calculated in Python, so the numbers are never guessed.
- A reviewer agent checks the plan and sends it back for fixes before you see it.
- If something is missing, like your departure city, it asks you.

## Results

Tested on 30 sample trips:

- Plans approved by the reviewer went from 35% on the first draft to 90% after fixing.
- Every plan stayed within budget or clearly said it couldn't.
- No made-up prices in any itinerary.

## Run it yourself

You need Python 3.11 and free keys from [Groq](https://console.groq.com/keys),
[SerpApi](https://serpapi.com) and [Tavily](https://app.tavily.com).

```
git clone https://github.com/farajt/yatra-ai.git
cd yatra-ai
pip install -r requirements.txt
copy .env.example .env      (then add your keys)
streamlit run streamlit_app.py
```

## Built with

LangGraph, Groq, Streamlit, SerpApi, Tavily and Open-Meteo.