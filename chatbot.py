# ==============================================
# MMA BRIDGE - LUCAS BOT (AI CHATBOT)
# Using OpenAI GPT-4
# ==============================================

import os
from openai import OpenAI
from database import get_all_fighters, get_all_events
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize OpenAI client
client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    timeout=30.0,
    max_retries=2
)

# ==============================================
# BUILD CONTEXT FROM DATABASE
# ==============================================

def build_mma_context(page_context='general'):
    """Build context about fighters and events for the chatbot"""
    
    try:
        # Get fighters data
        fighters = get_all_fighters()
        fighter_list = []
        for fighter_id, fighter in list(fighters.items())[:20]:  # Limit to 20 to save tokens
            fighter_list.append(
                f"{fighter['name']} ({fighter['weightClass']}): {fighter['record']}"
            )
        
        # Get events data
        events = get_all_events()
        event_list = []
        for event in events[:5]:  # Next 5 events
            event_list.append(
                f"{event['eventName']} - {event['date']} in {event['location']}"
            )
        
        # Base context
        base_context = f"""You are Lucas Bot, an MMA expert chatbot for MMA Bridge.

Current Fighters in Database:
{chr(10).join(fighter_list)}

Upcoming UFC Events:
{chr(10).join(event_list)}"""

        # Add page-specific context
        if page_context == 'pfp':
            base_context += """

CURRENT PAGE CONTEXT: User is viewing the Pound-For-Pound Rankings page.
- If they ask about rankings, refer to the fighters listed above
- If they ask why someone isn't ranked (like Jon Jones), explain he's currently inactive or not fighting regularly
- Be helpful about explaining P4P rankings and what makes a great pound-for-pound fighter"""
        
        elif page_context == 'events':
            base_context += """

CURRENT PAGE CONTEXT: User is viewing the Upcoming Events page.
- Focus on the upcoming events listed above
- Help them understand fight cards, matchups, and when events are happening
- Provide insights on interesting matchups"""
        
        elif page_context == 'home':
            base_context += """

CURRENT PAGE CONTEXT: User is on the homepage looking at trending MMA news.
- Provide general MMA news and analysis
- Discuss current hot topics in MMA"""
        
        base_context += """

You can answer questions about:
- Fighter records and stats
- Upcoming UFC events
- MMA news and analysis
- Fight predictions
- Weight classes and rankings
- Why certain fighters are or aren't on rankings

Be conversational, knowledgeable, and enthusiastic about MMA!"""
        
        return base_context
        
    except Exception as e:
        print(f"Error building context: {e}")
        return "You are Lucas Bot, an MMA expert chatbot."

# ==============================================
# CHAT WITH GPT-4
# ==============================================

def chat_with_lucas(user_message, conversation_history=[], page_context='general'):
    """
    Send message to GPT-4 and get response
    
    Args:
        user_message: The user's question
        conversation_history: List of previous messages [{"role": "user", "content": "..."}, ...]
        page_context: Current page user is on ('pfp', 'events', 'home', 'lucas', 'general')
    
    Returns:
        GPT-4's response text
    """
    
    try:
        # Build system context with page awareness
        system_context = build_mma_context(page_context)
        
        # Build message history
        messages = [
            {"role": "system", "content": system_context}
        ] + conversation_history + [
            {"role": "user", "content": user_message}
        ]
        
        # Call OpenAI API
        response = client.chat.completions.create(
            model="gpt-4-turbo-preview",  # or "gpt-4" or "gpt-3.5-turbo"
            messages=messages,
            max_tokens=1024,
            temperature=0.7
        )
        
        # Extract response text
        response_text = response.choices[0].message.content
        
        return response_text
        
    except Exception as e:
        print(f"Error calling OpenAI API: {e}")
        return "Sorry, I'm having trouble connecting right now. Please try again!"

# ==============================================
# TEST FUNCTION
# ==============================================

if __name__ == '__main__':
    print("=" * 50)
    print("🤖 LUCAS BOT TEST (OpenAI)")
    print("=" * 50)
    
    # Test question
    response = chat_with_lucas("Who is Islam Makhachev?")
    print(f"\nQuestion: Who is Islam Makhachev?")
    print(f"Lucas: {response}")
    print("\n" + "=" * 50)
