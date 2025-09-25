import ast
import operator as op
import requests
import json
from django.http import JsonResponse
import random
import time
from urllib.parse import quote

from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt

from .models import *
from django.db.models.functions import TruncDate
from django.db.models import Count

# Allowed operators mapping
_ALLOWED_OPERATORS = {
    ast.Add: op.add,
    ast.Sub: op.sub,
    ast.Mult: op.mul,
    ast.Div: op.truediv,
    ast.Mod: op.mod,
    ast.Pow: op.pow,
    ast.UAdd: op.pos,
    ast.USub: op.neg,
}
def customer(request,pk_test):
    customer=Customer.objects.get(id=pk_test)
    customers=Customer.objects.all()
    orders=customer.order_set.all()
    order_count=orders.count()
    context={'customers':customers, 'cust':customer,'orders':orders,'ordcount':order_count}
    return render(request,'customer.html',context)


def _safe_eval(node):
    """
    Recursively evaluate an AST node, permitting only numeric constants,
    binary ops (+, -, *, /, %, **), and unary +/-. Raises ValueError for
    any disallowed node.
    """
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)

    if isinstance(node, ast.BinOp):
        left = _safe_eval(node.left)
        right = _safe_eval(node.right)
        oper = _ALLOWED_OPERATORS.get(type(node.op))
        if oper is None:
            raise ValueError("Operator not allowed")
        return oper(left, right)

    if isinstance(node, ast.UnaryOp):
        operand = _safe_eval(node.operand)
        oper = _ALLOWED_OPERATORS.get(type(node.op))
        if oper is None:
            raise ValueError("Unary operator not allowed")
        return oper(operand)

    # For Python 3.8+, numeric literals are ast.Constant
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError("Only int/float constants are allowed")

    # For older Python versions
    if isinstance(node, ast.Num):
        return node.n

    raise ValueError("Unsupported expression")


@require_http_methods(["GET", "POST"])
def calculate(request):
    """
    Safe evaluate arithmetic expressions submitted via POST 'expression'.
    Handles special calculators and now accepts client-side computed results
    when the form posts with from_client=1 and client_result.
    """
    if request.method == "GET":
        return render(request, "home.html")

    calc_type = request.POST.get("calc_type", "simple")

    # If client did the calculation (scientific heavy functions), accept their result
    if request.POST.get("from_client") == "1" and request.POST.get("client_result") is not None:
        expr = request.POST.get("expression", "").strip() or request.POST.get("client_expression", "").strip()
        result = request.POST.get("client_result")
    else:
        # BMI calculator
        if calc_type == "bmi":
            try:
                weight = float(request.POST.get("weight", "").strip())
                height_cm = float(request.POST.get("height", "").strip())
                if weight <= 0 or height_cm <= 0:
                    raise ValueError("Weight and height must be positive numbers.")
                h_m = height_cm / 100.0
                bmi_val = weight / (h_m * h_m)
                bmi = round(bmi_val, 2)
                if bmi < 18.5:
                    category = "Underweight"
                elif bmi < 25:
                    category = "Normal"
                elif bmi < 30:
                    category = "Overweight"
                else:
                    category = "Obese"
                expr = f"{weight} kg / ({h_m} m)^2"
                result = f"{bmi} ({category})"
            except (ValueError, TypeError) as e:
                return render(request, "calculators/bmi.html", {"error": str(e)})
        # Age calculator
        elif calc_type == "age":
            from datetime import datetime, date
            bd = request.POST.get("birthdate", "").strip()
            try:
                if not bd:
                    raise ValueError("Please provide a birthdate.")
                birth = datetime.strptime(bd, "%Y-%m-%d").date()
                today = date.today()
                if birth > today:
                    raise ValueError("Birthdate cannot be in the future.")
                years = today.year - birth.year
                months = today.month - birth.month
                days = today.day - birth.day
                if days < 0:
                    from calendar import monthrange
                    prev_month = (today.month - 1) or 12
                    prev_year = today.year if today.month != 1 else today.year - 1
                    days_in_prev = monthrange(prev_year, prev_month)[1]
                    days += days_in_prev
                    months -= 1
                if months < 0:
                    months += 12
                    years -= 1
                expr = f"Birthdate: {birth.isoformat()}"
                parts = []
                if years: parts.append(f"{years}y")
                if months: parts.append(f"{months}m")
                if days or not parts: parts.append(f"{days}d")
                result = " ".join(parts)
            except (ValueError) as e:
                return render(request, "calculators/age.html", {"error": str(e)})
        # simple / scientific -> evaluate expression server-side (only basic math)
        else:
            expr = request.POST.get("expression", "").strip()
            if not expr:
                return render(request, f"calculators/{calc_type}.html", {"error": "Please enter an expression."})
            try:
                parsed = ast.parse(expr, mode="eval")
                for node in ast.walk(parsed):
                    if isinstance(node, (ast.Call, ast.Name, ast.Attribute, ast.Import, ast.ImportFrom, ast.Lambda)):
                        raise ValueError("Disallowed expression element")
                result = _safe_eval(parsed)
            except (SyntaxError, ValueError, ZeroDivisionError, OverflowError) as e:
                template = request.POST.get("return_template") or (f"calculators/{calc_type}.html" if calc_type else "calculators/simple.html")
                return render(request, template, {"error": f"Invalid expression: {e}", "expression": expr})

    # Save calculation record for history (store expression/result as strings)
    try:
        calc = Calculation(expression=str(expr), result=str(result))
        calc.save()
    except Exception:
        # non-critical: don't block response if model fails
        pass

    # Render back to originating template
    templates_map = {
        'simple': 'calculators/simple.html',
        'scientific': 'calculators/scientific.html',
        'bmi': 'calculators/bmi.html',
        'age': 'calculators/age.html'
    }
    return_template = request.POST.get('return_template') or templates_map.get(calc_type, 'home.html')
    context = {
        'expression': expr,
        'result': result,
        'calc_type': calc_type,
        'title': (calc_type.capitalize() + ' Calculator') if calc_type else 'Calculator'
    }
    return render(request, return_template, context)

def home(request):
    calculators = [
        {
            'id': 'simple',
            'name': 'Simple Calculator',
            'description': 'Basic arithmetic operations',
            'icon': '🔢',
            'open': 'Open Calculator'
        },
        {
            'id': 'scientific',
            'name': 'Scientific Calculator',
            'description': 'Advanced mathematical operations',
            'icon': '📐',
            'open': 'Open Calculator'
        },
        {
            'id': 'bmi',
            'name': 'BMI Calculator',
            'description': 'Body Mass Index Calculator',
            'icon': '⚖️',
            'open': 'Open Calculator'
        },
        {
            'id': 'age',
            'name': 'Age Calculator',
            'description': 'Calculate age from birthdate',
            'icon': '📅',
            'open': 'Open Calculator'
        },
    ]
    return render(request, 'home.html', {'calculators': calculators})

def dashboard(request):
    customers = Customer.objects.all()
    products = Product.objects.all()
    calculations = Calculation.objects.order_by('-timestamp')
    calc_count = Calculation.objects.count()
    daily_counts = (
        Calculation.objects
        .annotate(day=TruncDate('timestamp'))
        .values('day')
        .annotate(count=Count('id'))
        .order_by('day')
    )
    # Prepare data for Chart.js
    chart_labels = [str(item['day']) for item in daily_counts]
    chart_data = [item['count'] for item in daily_counts]
    return render(
        request,
        'dashboard.html',
        {
            'calculations': calculations,
            'calc_count': calc_count,
            'chart_labels': chart_labels,
            'chart_data': chart_data,
            'customers': customers,
            'products': products,
        }
    )

def settings(request):
    return render(request, 'settings.html')

def ChatGPT(request):
    return render(request, 'chatgpt.html')

def bootstrap(request):
    return render(request, 'bootstrap.html')

def delete_calculation(request, calc_id):
    if request.method == 'POST':
        calc = get_object_or_404(Calculation, id=calc_id)
        calc.delete()
    return redirect('dashboard')

def calculator(request, calc_type):
    templates = {
        'simple': 'calculators/simple.html',
        'scientific': 'calculators/scientific.html',
        'bmi': 'calculators/bmi.html',
        'age': 'calculators/age.html'
    }
    context = {
        'calc_type': calc_type,
        'title': calc_type.capitalize() + ' Calculator'
    }
    template = templates.get(calc_type, 'calculators/simple.html')
    return render(request, template, context)

def password(request):
    return render(request, 'password.html')

def meme_generator(request):
    return render(request, 'meme.html')

def get_meme_api(request):
    """API endpoint to fetch memes server-side to avoid CORS issues"""
    try:
        subreddit = request.GET.get('subreddit', 'memes')
        
        # List of available subreddits
        subreddits = [
            'memes', 'dankmemes', 'memeeconomy', 'wholesomememes', 
            'programmerhumor', 'historymemes', 'prequelmemes', 'me_irl',
            'funny', 'adviceanimals'
        ]
        
        if subreddit == 'random':
            subreddit = random.choice(subreddits)
        
        # Fetch from Reddit API
        headers = {
            'User-Agent': 'Django-Meme-Generator/1.0'
        }
        
        url = f'https://www.reddit.com/r/{subreddit}/hot.json?limit=50'
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code != 200:
            raise Exception(f'Reddit API returned status {response.status_code}')
        
        data = response.json()
        posts = data['data']['children']
        
        # Filter for image posts
        image_posts = []
        for post in posts:
            post_data = post['data']
            url = post_data.get('url', '')
            
            # Check if it's an image URL
            if any(ext in url.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif']) or \
               any(domain in url for domain in ['i.redd.it', 'i.imgur.com']):
                image_posts.append({
                    'title': post_data.get('title', ''),
                    'url': url,
                    'subreddit': post_data.get('subreddit', ''),
                    'score': post_data.get('score', 0),
                    'permalink': f"https://reddit.com{post_data.get('permalink', '')}"
                })
        
        if not image_posts:
            return JsonResponse({'error': 'No image posts found'}, status=404)
        
        # Return random post
        meme = random.choice(image_posts)
        return JsonResponse(meme)
        
    except requests.RequestException as e:
        return JsonResponse({'error': f'Network error: {str(e)}'}, status=500)
    except Exception as e:
        return JsonResponse({'error': f'Error fetching meme: {str(e)}'}, status=500)

def startup_ideas(request):
    return render(request, 'startup.html')

def webtoon_recommendations(request):
    return render(request, 'webtoons.html')

@csrf_exempt
def get_webtoon_api(request):
    """API endpoint to fetch real-time webtoon/manhwa recommendations from multiple sources"""
    try:
        genre = request.GET.get('genre', 'any')
        content_type = request.GET.get('type', 'any')
        status = request.GET.get('status', 'any')
        rating = request.GET.get('rating', 'any')
        
        webtoon_data = None
        
        # Try different APIs in order of preference
        try:
            # First try Webtoon-specific sources
            if content_type in ['webtoon', 'manhwa', 'any']:
                webtoon_data = fetch_from_webtoon_sources(genre, content_type, status, rating)
        except Exception as e:
            print(f"Webtoon sources failed: {e}")
        
        # Fallback to enhanced Reddit API
        if not webtoon_data:
            try:
                webtoon_data = fetch_enhanced_reddit_recommendations(genre, content_type, status)
            except Exception as e:
                print(f"Reddit API failed: {e}")
        
        # Final fallback to curated database with proper filtering
        if not webtoon_data:
            webtoon_data = get_curated_recommendation(genre, content_type, status, rating)
        
        return JsonResponse(webtoon_data)
        
    except Exception as e:
        return JsonResponse({'error': f'Error fetching recommendations: {str(e)}'}, status=500)

def fetch_from_webtoon_sources(genre, content_type, status, rating):
    """Fetch from webtoon-specific sources"""
    try:
        # Use a combination of sources for better webtoon coverage
        
        # Try AniList API which has better webtoon/manhwa coverage
        webtoon_data = fetch_from_anilist_api(genre, content_type, status)
        if webtoon_data:
            return webtoon_data
            
        # Try Kitsu API as backup
        webtoon_data = fetch_from_kitsu_api(genre, content_type)
        if webtoon_data:
            return webtoon_data
            
        raise Exception("No webtoon sources available")
        
    except Exception as e:
        raise Exception(f"Webtoon sources error: {str(e)}")

def fetch_from_anilist_api(genre, content_type, status):
    """Fetch from AniList API which has better manhwa/webtoon coverage"""
    try:
        # AniList GraphQL API
        url = 'https://graphql.anilist.co'
        
        # Map our types to AniList formats
        format_mapping = {
            'webtoon': ['MANGA'],  # AniList doesn't distinguish webtoons specifically
            'manhwa': ['MANGA'],
            'manhua': ['MANGA'],
            'manga': ['MANGA'],
            'any': ['MANGA']
        }
        
        # Map our genres to AniList genres
        genre_mapping = {
            'action': 'Action',
            'romance': 'Romance',
            'comedy': 'Comedy',
            'drama': 'Drama',
            'fantasy': 'Fantasy',
            'horror': 'Horror',
            'mystery': 'Mystery',
            'slice-of-life': 'Slice of Life',
            'supernatural': 'Supernatural',
            'sci-fi': 'Sci-Fi',
            'thriller': 'Thriller',
            'historical': 'Historical'
        }
        
        # Map status
        status_mapping = {
            'ongoing': 'RELEASING',
            'completed': 'FINISHED',
            'hiatus': 'HIATUS',
            'any': None
        }
        
        # Build GraphQL query
        query = '''
        query ($page: Int, $perPage: Int, $genre: String, $status: MediaStatus, $countryOfOrigin: CountryCode) {
            Page(page: $page, perPage: $perPage) {
                media(type: MANGA, genre: $genre, status: $status, countryOfOrigin: $countryOfOrigin, sort: SCORE_DESC) {
                    id
                    title {
                        romaji
                        english
                        native
                    }
                    description
                    status
                    chapters
                    averageScore
                    genres
                    startDate {
                        year
                    }
                    staff {
                        nodes {
                            name {
                                full
                            }
                        }
                    }
                    countryOfOrigin
                    coverImage {
                        large
                    }
                    siteUrl
                }
            }
        }
        '''
        
        # Set variables based on content type
        variables = {
            'page': 1,
            'perPage': 50
        }
        
        if genre != 'any' and genre in genre_mapping:
            variables['genre'] = genre_mapping[genre]
            
        if status != 'any':
            variables['status'] = status_mapping.get(status)
            
        # Focus on Korean/Chinese content for webtoons/manhwa
        if content_type in ['webtoon', 'manhwa']:
            variables['countryOfOrigin'] = 'KR'  # Korea
        elif content_type == 'manhua':
            variables['countryOfOrigin'] = 'CN'  # China
        elif content_type == 'manga':
            variables['countryOfOrigin'] = 'JP'  # Japan
        
        response = requests.post(
            url, 
            json={'query': query, 'variables': variables},
            headers={'User-Agent': 'Django-Webtoon-Finder/1.0'},
            timeout=10
        )
        
        if response.status_code != 200:
            raise Exception(f'AniList API returned status {response.status_code}')
        
        data = response.json()
        
        if not data.get('data', {}).get('Page', {}).get('media'):
            raise Exception('No media found from AniList')
        
        media_list = data['data']['Page']['media']
        
        if media_list:
            selected = random.choice(media_list)
            
            # Get the best title
            title = (selected['title'].get('english') or 
                    selected['title'].get('romaji') or 
                    selected['title'].get('native') or 
                    'Unknown Title')
            
            # Get author from staff
            author = 'Unknown Author'
            if selected.get('staff', {}).get('nodes'):
                author = selected['staff']['nodes'][0]['name']['full']
            
            # Map status back to our format
            api_status = selected.get('status', '')
            mapped_status = {
                'RELEASING': 'ongoing',
                'FINISHED': 'completed',
                'HIATUS': 'hiatus',
                'CANCELLED': 'hiatus'
            }.get(api_status, 'ongoing')
            
            # Determine actual content type based on origin
            origin_country = selected.get('countryOfOrigin', '')
            actual_type = {
                'KR': 'manhwa',
                'CN': 'manhua', 
                'JP': 'manga'
            }.get(origin_country, 'manga')
            
            # If user requested webtoon, and it's Korean, call it webtoon
            if content_type == 'webtoon' and origin_country == 'KR':
                actual_type = 'webtoon'
            
            webtoon_data = {
                'title': title,
                'type': actual_type,
                'genre': genre if genre != 'any' else (selected.get('genres', ['Action'])[0].lower() if selected.get('genres') else 'action'),
                'status': mapped_status,
                'rating': round(selected.get('averageScore', 0) / 10, 1) if selected.get('averageScore') else 4.0,
                'author': author,
                'year': selected.get('startDate', {}).get('year', 2020) or 2020,
                'chapters': selected.get('chapters') or 'Unknown',
                'origin': {
                    'KR': 'South Korea',
                    'CN': 'China',
                    'JP': 'Japan'
                }.get(origin_country, 'Unknown'),
                'description': clean_description(selected.get('description', 'No description available.')),
                'tags': selected.get('genres', [])[:3],
                'source': 'AniList API',
                'image_url': selected.get('coverImage', {}).get('large', ''),
                'url': selected.get('siteUrl', '')
            }
            
            return webtoon_data
        
        raise Exception('No suitable content found')
        
    except Exception as e:
        raise Exception(f'AniList API error: {str(e)}')

def fetch_from_kitsu_api(genre, content_type):
    """Fetch from Kitsu API as backup"""
    try:
        base_url = "https://kitsu.io/api/edge/manga"
        
        params = {
            'page[limit]': 20,
            'sort': '-averageRating'
        }
        
        # Add filters
        if genre != 'any':
            params['filter[genres]'] = genre.title()
        
        headers = {
            'Accept': 'application/vnd.api+json',
            'Content-Type': 'application/vnd.api+json',
            'User-Agent': 'Django-Webtoon-Finder/1.0'
        }
        
        response = requests.get(base_url, params=params, headers=headers, timeout=10)
        
        if response.status_code != 200:
            raise Exception(f'Kitsu API returned status {response.status_code}')
        
        data = response.json()
        
        if not data.get('data'):
            raise Exception('No data from Kitsu API')
        
        manga_list = data['data']
        
        # Filter for webtoons/manhwa based on title patterns and description
        filtered_list = []
        for manga in manga_list:
            attributes = manga.get('attributes', {})
            title = attributes.get('canonicalTitle', '')
            description = attributes.get('synopsis', '')
            
            # Simple heuristic to identify webtoons/manhwa
            is_likely_webtoon = any(keyword in title.lower() or keyword in description.lower() 
                                  for keyword in ['korean', 'webtoon', 'manhwa', 'naver', 'kakao'])
            
            if content_type in ['webtoon', 'manhwa', 'any'] and is_likely_webtoon:
                filtered_list.append(manga)
            elif content_type in ['manga', 'any']:
                filtered_list.append(manga)
        
        if filtered_list:
            selected = random.choice(filtered_list)
            attributes = selected['attributes']
            
            webtoon_data = {
                'title': attributes.get('canonicalTitle', 'Unknown Title'),
                'type': 'webtoon' if content_type == 'webtoon' else 'manhwa',
                'genre': genre if genre != 'any' else 'action',
                'status': map_kitsu_status(attributes.get('status', '')),
                'rating': round(float(attributes.get('averageRating', 0)) / 10, 1) if attributes.get('averageRating') else 4.0,
                'author': 'Unknown Author',  # Kitsu doesn't easily provide author info
                'year': int(attributes.get('startDate', '2020')[:4]) if attributes.get('startDate') else 2020,
                'chapters': attributes.get('chapterCount') or 'Unknown',
                'origin': 'South Korea' if 'webtoon' in content_type else 'Unknown',
                'description': clean_description(attributes.get('synopsis', 'No description available.')),
                'tags': [],
                'source': 'Kitsu API',
                'image_url': attributes.get('posterImage', {}).get('large', '') if attributes.get('posterImage') else '',
                'url': f"https://kitsu.io/manga/{selected.get('id', '')}"
            }
            
            return webtoon_data
        
        raise Exception('No suitable content found in Kitsu')
        
    except Exception as e:
        raise Exception(f'Kitsu API error: {str(e)}')

def fetch_enhanced_reddit_recommendations(genre, content_type, status):
    """Enhanced Reddit fetching with better filtering"""
    try:
        # Choose subreddit based on content type
        subreddit_mapping = {
            'webtoon': ['webtoons', 'manhwa', 'OtomeIsekai'],
            'manhwa': ['manhwa', 'manhwareccomendations', 'OtomeIsekai'],
            'manhua': ['manhua', 'manga'],
            'manga': ['manga', 'MangaRecommendations'],
            'any': ['webtoons', 'manhwa', 'manga', 'OtomeIsekai']
        }
        
        subreddits = subreddit_mapping.get(content_type, ['webtoons', 'manhwa'])
        selected_subreddit = random.choice(subreddits)
        
        headers = {
            'User-Agent': 'Django-Webtoon-Finder/1.0'
        }
        
        # Build search query
        search_terms = ['recommend', 'suggestion', 'best']
        if genre != 'any':
            search_terms.append(genre)
        if content_type != 'any':
            search_terms.append(content_type)
            
        search_query = ' OR '.join(search_terms)
        url = f'https://www.reddit.com/r/{selected_subreddit}/search.json?q={quote(search_query)}&limit=50&sort=top&t=month'
        
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code != 200:
            raise Exception(f'Reddit API returned status {response.status_code}')
        
        data = response.json()
        posts = data['data']['children']
        
        # Enhanced title extraction with better patterns
        recommendations = extract_enhanced_recommendations(posts, genre, content_type, status)
        
        if recommendations:
            return random.choice(recommendations)
        
        raise Exception('No recommendations found in Reddit')
        
    except Exception as e:
        raise Exception(f'Enhanced Reddit API error: {str(e)}')

def extract_enhanced_recommendations(posts, genre, content_type, status):
    """Enhanced recommendation extraction with better title recognition"""
    recommendations = []
    
    # Expanded title database with more metadata
    enhanced_titles = {
        # Webtoons
        'Tower of God': {'type': 'webtoon', 'genre': 'action', 'status': 'ongoing', 'rating': 4.7, 'origin': 'South Korea'},
        'Noblesse': {'type': 'webtoon', 'genre': 'action', 'status': 'completed', 'rating': 4.5, 'origin': 'South Korea'},
        'The God of High School': {'type': 'webtoon', 'genre': 'action', 'status': 'ongoing', 'rating': 4.6, 'origin': 'South Korea'},
        'Hardcore Leveling Warrior': {'type': 'webtoon', 'genre': 'action', 'status': 'ongoing', 'rating': 4.4, 'origin': 'South Korea'},
        'UnOrdinary': {'type': 'webtoon', 'genre': 'supernatural', 'status': 'ongoing', 'rating': 4.5, 'origin': 'South Korea'},
        'True Beauty': {'type': 'webtoon', 'genre': 'romance', 'status': 'completed', 'rating': 4.5, 'origin': 'South Korea'},
        'Let\'s Play': {'type': 'webtoon', 'genre': 'romance', 'status': 'ongoing', 'rating': 4.2, 'origin': 'South Korea'},
        'I Love Yoo': {'type': 'webtoon', 'genre': 'drama', 'status': 'ongoing', 'rating': 4.6, 'origin': 'South Korea'},
        'Lore Olympus': {'type': 'webtoon', 'genre': 'romance', 'status': 'ongoing', 'rating': 4.6, 'origin': 'New Zealand'},
        'My Dear Cold-Blooded King': {'type': 'webtoon', 'genre': 'romance', 'status': 'completed', 'rating': 4.3, 'origin': 'South Korea'},
        
        # Manhwa
        'Solo Leveling': {'type': 'manhwa', 'genre': 'action', 'status': 'completed', 'rating': 4.9, 'origin': 'South Korea'},
        'The Beginning After The End': {'type': 'manhwa', 'genre': 'fantasy', 'status': 'ongoing', 'rating': 4.7, 'origin': 'South Korea'},
        'Omniscient Reader\'s Viewpoint': {'type': 'manhwa', 'genre': 'fantasy', 'status': 'ongoing', 'rating': 4.9, 'origin': 'South Korea'},
        'Eleceed': {'type': 'manhwa', 'genre': 'action', 'status': 'ongoing', 'rating': 4.8, 'origin': 'South Korea'},
        'Weak Hero': {'type': 'manhwa', 'genre': 'action', 'status': 'ongoing', 'rating': 4.8, 'origin': 'South Korea'},
        'The Remarried Empress': {'type': 'manhwa', 'genre': 'drama', 'status': 'ongoing', 'rating': 4.7, 'origin': 'South Korea'},
        'Who Made Me a Princess': {'type': 'manhwa', 'genre': 'fantasy', 'status': 'completed', 'rating': 4.6, 'origin': 'South Korea'},
        'Bastard': {'type': 'manhwa', 'genre': 'thriller', 'status': 'completed', 'rating': 4.6, 'origin': 'South Korea'},
        'Sweet Home': {'type': 'manhwa', 'genre': 'horror', 'status': 'completed', 'rating': 4.4, 'origin': 'South Korea'},
        'Lookism': {'type': 'manhwa', 'genre': 'drama', 'status': 'ongoing', 'rating': 4.5, 'origin': 'South Korea'},
        
        # Manhua
        'Tales of Demons and Gods': {'type': 'manhua', 'genre': 'fantasy', 'status': 'ongoing', 'rating': 4.3, 'origin': 'China'},
        'Battle Through the Heavens': {'type': 'manhua', 'genre': 'fantasy', 'status': 'ongoing', 'rating': 4.2, 'origin': 'China'},
        'The King\'s Avatar': {'type': 'manhua', 'genre': 'action', 'status': 'ongoing', 'rating': 4.4, 'origin': 'China'},
        'Spirit Blade Mountain': {'type': 'manhua', 'genre': 'fantasy', 'status': 'ongoing', 'rating': 4.1, 'origin': 'China'},
    }
    
    for post in posts:
        post_data = post['data']
        title_text = post_data.get('title', '').lower()
        selftext = post_data.get('selftext', '').lower()
        combined_text = f"{title_text} {selftext}"
        
        # Look for titles in the text
        for known_title, metadata in enhanced_titles.items():
            if known_title.lower() in combined_text:
                # Check if it matches our filters
                if (content_type == 'any' or metadata['type'] == content_type) and \
                   (genre == 'any' or metadata['genre'] == genre) and \
                   (status == 'any' or metadata['status'] == status):
                    
                    # Generate full recommendation
                    rec = generate_enhanced_recommendation(known_title, metadata)
                    if rec:
                        recommendations.append(rec)
                        break  # Only add one per post
    
    return recommendations

def generate_enhanced_recommendation(title, metadata):
    """Generate a full recommendation from title and metadata"""
    # Extended database with full information
    full_database = {
        'Solo Leveling': {
            'author': 'Chugong', 'year': 2018, 'chapters': '179',
            'description': 'Sung Jin-Woo was the weakest E-Rank hunter until a mysterious System grants him the power to level up infinitely.',
            'tags': ['RPG', 'Monsters', 'Power Fantasy']
        },
        'Tower of God': {
            'author': 'SIU', 'year': 2010, 'chapters': '500+',
            'description': 'Twenty-Fifth Baam enters the Tower of God, a mysterious structure where each floor presents deadly challenges. Follow his journey to reach the top and find his friend Rachel.',
            'tags': ['Adventure', 'Supernatural', 'Mystery']
        },
        'True Beauty': {
            'author': 'Yaongyi', 'year': 2018, 'chapters': '230',
            'description': 'Lim Ju-kyung uses makeup to hide her perceived flaws in this story about self-acceptance and young love.',
            'tags': ['School', 'Beauty', 'Self-esteem']
        },
        'Omniscient Reader\'s Viewpoint': {
            'author': 'sing N song', 'year': 2020, 'chapters': '120+',
            'description': 'Kim Dokja was the sole reader of a web novel for 10 years. When the story becomes reality, he\'s the only one who knows how to survive.',
            'tags': ['Apocalypse', 'Meta-fiction', 'Survival']
        }
        # Add more as needed
    }
    
    if title in full_database:
        full_info = full_database[title]
        return {
            'title': title,
            'type': metadata['type'],
            'genre': metadata['genre'],
            'status': metadata['status'],
            'rating': metadata['rating'],
            'author': full_info['author'],
            'year': full_info['year'],
            'chapters': full_info['chapters'],
            'origin': metadata['origin'],
            'description': full_info['description'],
            'tags': full_info['tags'],
            'source': 'Enhanced Reddit API'
        }
    
    return None

def map_kitsu_status(status):
    """Map Kitsu status to our format"""
    status_mapping = {
        'current': 'ongoing',
        'finished': 'completed',
        'tba': 'ongoing',
        'unreleased': 'upcoming',
        'upcoming': 'upcoming'
    }
    return status_mapping.get(status, 'ongoing')

# Update the existing get_curated_recommendation function to have better filtering
def get_curated_recommendation(genre, content_type, status, rating):
    """Enhanced fallback to our curated database with proper filtering"""
    # Use the comprehensive database from before
    webtoons = [
        {
            'title': "Solo Leveling",
            'type': "manhwa",
            'genre': "action",
            'status': "completed",
            'rating': 4.9,
            'author': "Chugong",
            'year': 2018,
            'chapters': "179",
            'origin': "South Korea",
            'description': "Sung Jin-Woo was the weakest E-Rank hunter until a mysterious System grants him the power to level up infinitely. Watch as he becomes the world's strongest hunter.",
            'tags': ["RPG", "Monsters", "Power Fantasy"],
            'source': 'Curated Database'
        },
        {
            'title': "Tower of God",
            'type': "webtoon",
            'genre': "action",
            'status': "ongoing",
            'rating': 4.7,
            'author': "SIU",
            'year': 2010,
            'chapters': "500+",
            'origin': "South Korea",
            'description': "Twenty-Fifth Baam enters the Tower of God, a mysterious structure where each floor presents deadly challenges. Follow his journey to reach the top and find his friend Rachel.",
            'tags': ["Adventure", "Supernatural", "Mystery"],
            'source': 'Curated Database'
        },
        {
            'title': "True Beauty",
            'type': "webtoon",
            'genre': "romance",
            'status': "completed",
            'rating': 4.5,
            'author': "Yaongyi",
            'year': 2018,
            'chapters': "230",
            'origin': "South Korea",
            'description': "Lim Ju-kyung is a high school student who uses makeup to hide her perceived flaws. A sweet romantic story about self-acceptance and young love.",
            'tags': ["School", "Beauty", "Self-esteem"],
            'source': 'Curated Database'
        },
        {
            'title': "Omniscient Reader's Viewpoint",
            'type': "manhwa",
            'genre': "fantasy",
            'status': "ongoing",
            'rating': 4.9,
            'author': "sing N song",
            'year': 2020,
            'chapters': "120+",
            'origin': "South Korea",
            'description': "Kim Dokja was the sole reader of a web novel for 10 years. When the story becomes reality, he's the only one who knows how to survive.",
            'tags': ["Apocalypse", "Meta-fiction", "Survival"],
            'source': 'Curated Database'
        },
        {
            'title': "The Beginning After The End",
            'type': "manhwa",
            'genre': "fantasy",
            'status': "ongoing",
            'rating': 4.7,
            'author': "TurtleMe",
            'year': 2018,
            'chapters': "150+",
            'origin': "South Korea",
            'description': "King Grey is reborn in a world of magic and monsters. With his past life's knowledge, he seeks to correct his previous mistakes.",
            'tags': ["Reincarnation", "Magic", "Second Chance"],
            'source': 'Curated Database'
        },
        {
            'title': "Romance 101",
            'type': "webtoon",
            'genre': "romance",
            'status': "ongoing",
            'rating': 4.4,
            'author': "Namsoo",
            'year': 2019,
            'chapters': "120+",
            'origin': "South Korea",
            'description': "Bareum, who has given up on dating, finds herself in a fake relationship that might become something real. A mature take on modern romance.",
            'tags': ["College", "Fake Dating", "Mature"],
            'source': 'Curated Database'
        },
        {
            'title': "Tales of Demons and Gods",
            'type': "manhua",
            'genre': "fantasy",
            'status': "ongoing",
            'rating': 4.3,
            'author': "Mad Snail",
            'year': 2015,
            'chapters': "400+",
            'origin': "China",
            'description': "Nie Li is killed and reborn back to when he was thirteen. With his previous life's knowledge, he works to change his fate and protect his city.",
            'tags': ["Reincarnation", "Cultivation", "Time Travel"],
            'source': 'Curated Database'
        },
        {
            'title': "UnOrdinary",
            'type': "webtoon",
            'genre': "supernatural",
            'status': "ongoing",
            'rating': 4.5,
            'author': "uru-chan",
            'year': 2016,
            'chapters': "270+",
            'origin': "South Korea",
            'description': "In a world where supernatural abilities are the norm, John pretends to be powerless while hiding his devastating strength.",
            'tags': ["School", "Superpowers", "Hidden Identity"],
            'source': 'Curated Database'
        },
        {
            'title': "Eleceed",
            'type': "manhwa",
            'genre': "action",
            'status': "ongoing",
            'rating': 4.8,
            'author': "Son Jeho",
            'year': 2018,
            'chapters': "250+",
            'origin': "South Korea",
            'description': "Jiwoo has the power of super speed, and when he meets Kayden (stuck in a cat's body), he enters the world of awakened beings.",
            'tags': ["Superpowers", "Mentorship", "Comedy"],
            'source': 'Curated Database'
        },
        {
            'title': "Sweet Home",
            'type': "manhwa",
            'genre': "horror",
            'status': "completed",
            'rating': 4.4,
            'author': "Carnby Kim",
            'year': 2017,
            'chapters': "140",
            'origin': "South Korea",
            'description': "Cha Hyun-soo moves into a new apartment just as monsters begin transforming from humans driven by their deepest desires.",
            'tags': ["Apocalypse", "Survival", "Psychological"],
            'source': 'Curated Database'
        }
    ]
    
    # Enhanced filtering with proper type checking
    filtered = []
    min_rating = float(rating) if rating != 'any' and rating else 0.0
    
    for webtoon in webtoons:
        genre_match = (genre == 'any' or webtoon['genre'] == genre)
        type_match = (content_type == 'any' or webtoon['type'] == content_type)
        status_match = (status == 'any' or webtoon['status'] == status)
        rating_match = (rating == 'any' or webtoon['rating'] >= min_rating)
        
        if genre_match and type_match and status_match and rating_match:
            filtered.append(webtoon)
    
    if filtered:
        return random.choice(filtered)
    else:
        # If no exact matches, return a random one but prioritize type match
        type_matches = [w for w in webtoons if content_type == 'any' or w['type'] == content_type]
        if type_matches:
            return random.choice(type_matches)
        else:
            return random.choice(webtoons)

def movie_recommendations(request):
    return render(request, 'movies.html')

@csrf_exempt
def get_movie_api(request):
    """API endpoint to fetch real-time movie/TV show recommendations from multiple sources"""
    try:
        genre = request.GET.get('genre', 'any')
        content_type = request.GET.get('type', 'any')
        year = request.GET.get('year', 'any')
        rating = request.GET.get('rating', 'any')
        
        movie_data = None
        
        # Try different APIs in order of preference
        try:
            # First try TMDB API (primary source for movies/TV)
            if content_type in ['movie', 'tv', 'any']:
                movie_data = fetch_from_tmdb_api(genre, content_type, year, rating)
        except Exception as e:
            print(f"TMDB API failed: {e}")
        
        # Fallback to OMDB API
        if not movie_data:
            try:
                movie_data = fetch_from_omdb_api(genre, content_type, year, rating)
            except Exception as e:
                print(f"OMDB API failed: {e}")
        
        # Fallback to enhanced Reddit API
        if not movie_data:
            try:
                movie_data = fetch_movie_reddit_recommendations(genre, content_type)
            except Exception as e:
                print(f"Reddit API failed: {e}")
        
        # Final fallback to curated database
        if not movie_data:
            movie_data = get_curated_movie_recommendation(genre, content_type, year, rating)
        
        return JsonResponse(movie_data)
        
    except Exception as e:
        return JsonResponse({'error': f'Error fetching movie recommendations: {str(e)}'}, status=500)

def fetch_from_tmdb_api(genre, content_type, year, rating):
    """Fetch from The Movie Database (TMDB) API"""
    try:
        # TMDB API key would be needed for production
        # For this example, we'll simulate the API structure
        base_url = "https://api.themoviedb.org/3"
        
        # Map our content types to TMDB
        type_mapping = {
            'movie': 'movie',
            'tv': 'tv',
            'any': random.choice(['movie', 'tv'])
        }
        
        tmdb_type = type_mapping.get(content_type, 'movie')
        
        # Genre mapping for TMDB
        genre_mapping = {
            'action': 28, 'adventure': 12, 'animation': 16, 'comedy': 35,
            'crime': 80, 'documentary': 99, 'drama': 18, 'family': 10751,
            'fantasy': 14, 'history': 36, 'horror': 27, 'music': 10402,
            'mystery': 9648, 'romance': 10749, 'sci-fi': 878, 'thriller': 53,
            'war': 10752, 'western': 37
        }
        
        # For this example, we'll use a curated response similar to TMDB structure
        # In production, you'd make actual API calls with your API key
        
        # Simulate popular movies/shows based on filters
        popular_content = get_popular_content_by_filters(genre, content_type, year, rating)
        
        if popular_content:
            selected = random.choice(popular_content)
            return format_tmdb_response(selected, tmdb_type)
        
        raise Exception('No content found from TMDB simulation')
        
    except Exception as e:
        raise Exception(f'TMDB API error: {str(e)}')

def get_popular_content_by_filters(genre, content_type, year, rating):
    """Get popular content based on filters (simulating TMDB data)"""
    
    # Comprehensive database of popular movies and TV shows
    content_database = [
        # Movies
        {
            'title': 'The Dark Knight',
            'type': 'movie',
            'genre': 'action',
            'year': 2008,
            'rating': 9.0,
            'director': 'Christopher Nolan',
            'cast': ['Christian Bale', 'Heath Ledger', 'Aaron Eckhart'],
            'runtime': 152,
            'description': 'When the menace known as the Joker wreaks havoc and chaos on the people of Gotham, Batman must accept one of the greatest psychological and physical tests.',
            'poster': 'https://image.tmdb.org/t/p/w500/qJ2tW6WMUDux911r6m7haRef0WH.jpg'
        },
        {
            'title': 'Inception',
            'type': 'movie',
            'genre': 'sci-fi',
            'year': 2010,
            'rating': 8.8,
            'director': 'Christopher Nolan',
            'cast': ['Leonardo DiCaprio', 'Marion Cotillard', 'Tom Hardy'],
            'runtime': 148,
            'description': 'A thief who steals corporate secrets through dream-sharing technology is given the inverse task of planting an idea into the mind of a C.E.O.',
            'poster': 'https://image.tmdb.org/t/p/w500/9gk7adHYeDvHkCSEqAvQNLV5Uge.jpg'
        },
        {
            'title': 'Parasite',
            'type': 'movie',
            'genre': 'thriller',
            'year': 2019,
            'rating': 8.6,
            'director': 'Bong Joon-ho',
            'cast': ['Song Kang-ho', 'Lee Sun-kyun', 'Cho Yeo-jeong'],
            'runtime': 132,
            'description': 'A poor family schemes to become employed by a wealthy family and infiltrate their household by posing as unrelated, highly qualified individuals.',
            'poster': 'https://image.tmdb.org/t/p/w500/7IiTTgloJzvGI1TAYymCfbfl3vT.jpg'
        },
        {
            'title': 'Spirited Away',
            'type': 'movie',
            'genre': 'animation',
            'year': 2001,
            'rating': 9.2,
            'director': 'Hayao Miyazaki',
            'cast': ['Rumi Hiiragi', 'Miyu Irino', 'Mari Natsuki'],
            'runtime': 125,
            'description': 'During her family\'s move to the suburbs, a sullen 10-year-old girl wanders into a world ruled by gods, witches, and spirits.',
            'poster': 'https://image.tmdb.org/t/p/w500/39wmItIWsg5sZMyRUHLkWBcuVCM.jpg'
        },
        {
            'title': 'The Godfather',
            'type': 'movie',
            'genre': 'crime',
            'year': 1972,
            'rating': 9.2,
            'director': 'Francis Ford Coppola',
            'cast': ['Marlon Brando', 'Al Pacino', 'James Caan'],
            'runtime': 175,
            'description': 'The aging patriarch of an organized crime dynasty transfers control of his clandestine empire to his reluctant son.',
            'poster': 'https://image.tmdb.org/t/p/w500/3bhkrj58Vtu7enYsRolD1fZdja1.jpg'
        },
        {
            'title': 'Pulp Fiction',
            'type': 'movie',
            'genre': 'crime',
            'year': 1994,
            'rating': 8.9,
            'director': 'Quentin Tarantino',
            'cast': ['John Travolta', 'Uma Thurman', 'Samuel L. Jackson'],
            'runtime': 154,
            'description': 'The lives of two mob hitmen, a boxer, a gangster and his wife intertwine in four tales of violence and redemption.',
            'poster': 'https://image.tmdb.org/t/p/w500/d5iIlFn5s0ImszYzBPb8JPIfbXD.jpg'
        },
        {
            'title': 'Interstellar',
            'type': 'movie',
            'genre': 'sci-fi',
            'year': 2014,
            'rating': 8.6,
            'director': 'Christopher Nolan',
            'cast': ['Matthew McConaughey', 'Anne Hathaway', 'Jessica Chastain'],
            'runtime': 169,
            'description': 'A team of explorers travel through a wormhole in space in an attempt to ensure humanity\'s survival.',
            'poster': 'https://image.tmdb.org/t/p/w500/gEU2QniE6E77NI6lCU6MxlNBvIx.jpg'
        },
        {
            'title': 'The Shawshank Redemption',
            'type': 'movie',
            'genre': 'drama',
            'year': 1994,
            'rating': 9.3,
            'director': 'Frank Darabont',
            'cast': ['Tim Robbins', 'Morgan Freeman', 'Bob Gunton'],
            'runtime': 142,
            'description': 'Two imprisoned men bond over a number of years, finding solace and eventual redemption through acts of common decency.',
            'poster': 'https://image.tmdb.org/t/p/w500/q6y0Go1tsGEsmtFryDOJo3dEmqu.jpg'
        },
        
        # TV Shows
        {
            'title': 'Breaking Bad',
            'type': 'tv',
            'genre': 'crime',
            'year': 2008,
            'rating': 9.5,
            'director': 'Vince Gilligan',
            'cast': ['Bryan Cranston', 'Aaron Paul', 'Anna Gunn'],
            'runtime': 47,
            'seasons': 5,
            'episodes': 62,
            'description': 'A high school chemistry teacher diagnosed with inoperable lung cancer turns to manufacturing and selling methamphetamine.',
            'poster': 'https://image.tmdb.org/t/p/w500/ggFHVNu6YYI5L9pCfOacjizRGt.jpg'
        },
        {
            'title': 'Game of Thrones',
            'type': 'tv',
            'genre': 'fantasy',
            'year': 2011,
            'rating': 8.7,
            'director': 'David Benioff',
            'cast': ['Emilia Clarke', 'Peter Dinklage', 'Kit Harington'],
            'runtime': 57,
            'seasons': 8,
            'episodes': 73,
            'description': 'Nine noble families fight for control over the lands of Westeros, while an ancient enemy returns after being dormant for millennia.',
            'poster': 'https://image.tmdb.org/t/p/w500/u3bZgnGQ9T01sWNhyveQz0wH0Hl.jpg'
        },
        {
            'title': 'Stranger Things',
            'type': 'tv',
            'genre': 'sci-fi',
            'year': 2016,
            'rating': 8.7,
            'director': 'The Duffer Brothers',
            'cast': ['Millie Bobby Brown', 'Finn Wolfhard', 'Winona Ryder'],
            'runtime': 51,
            'seasons': 4,
            'episodes': 42,
            'description': 'When a young boy disappears, his mother, a police chief and his friends must confront terrifying supernatural forces.',
            'poster': 'https://image.tmdb.org/t/p/w500/x2LSRK2Cm7MZhjluni1msVJ3wDF.jpg'
        },
        {
            'title': 'The Office',
            'type': 'tv',
            'genre': 'comedy',
            'year': 2005,
            'rating': 8.9,
            'director': 'Greg Daniels',
            'cast': ['Steve Carell', 'John Krasinski', 'Jenna Fischer'],
            'runtime': 22,
            'seasons': 9,
            'episodes': 201,
            'description': 'A mockumentary on a group of typical office workers, where the workday consists of ego clashes, inappropriate behavior.',
            'poster': 'https://image.tmdb.org/t/p/w500/qWnJzyZhyy74gjpSjIXWmuk0ifX.jpg'
        },
        {
            'title': 'Friends',
            'type': 'tv',
            'genre': 'comedy',
            'year': 1994,
            'rating': 8.9,
            'director': 'David Crane',
            'cast': ['Jennifer Aniston', 'Courteney Cox', 'Lisa Kudrow'],
            'runtime': 22,
            'seasons': 10,
            'episodes': 236,
            'description': 'Follows the personal and professional lives of six twenty to thirty-something-year-old friends living in Manhattan.',
            'poster': 'https://image.tmdb.org/t/p/w500/f496cm9enuEsZkSPzCwnTESEK5s.jpg'
        },
        {
            'title': 'The Crown',
            'type': 'tv',
            'genre': 'drama',
            'year': 2016,
            'rating': 8.7,
            'director': 'Peter Morgan',
            'cast': ['Claire Foy', 'Olivia Colman', 'Imelda Staunton'],
            'runtime': 58,
            'seasons': 6,
            'episodes': 60,
            'description': 'Follows the political rivalries and romance of Queen Elizabeth II\'s reign and the events that shaped the second half of the 20th century.',
            'poster': 'https://image.tmdb.org/t/p/w500/1M876KQUEUp3dcTn6wXcjOoSjbA.jpg'
        },
        {
            'title': 'The Mandalorian',
            'type': 'tv',
            'genre': 'sci-fi',
            'year': 2019,
            'rating': 8.7,
            'director': 'Jon Favreau',
            'cast': ['Pedro Pascal', 'Gina Carano', 'Carl Weathers'],
            'runtime': 40,
            'seasons': 3,
            'episodes': 24,
            'description': 'The travels of a lone bounty hunter in the outer reaches of the galaxy, far from the authority of the New Republic.',
            'poster': 'https://image.tmdb.org/t/p/w500/sWgBv7LV2PRoQgkxwlibdGXKz1S.jpg'
        },
        {
            'title': 'Squid Game',
            'type': 'tv',
            'genre': 'thriller',
            'year': 2021,
            'rating': 8.0,
            'director': 'Hwang Dong-hyuk',
            'cast': ['Lee Jung-jae', 'Park Hae-soo', 'Wi Ha-joon'],
            'runtime': 56,
            'seasons': 1,
            'episodes': 9,
            'description': 'Hundreds of cash-strapped players accept a strange invitation to compete in children\'s games for a tempting prize.',
            'poster': 'https://image.tmdb.org/t/p/w500/dDlEmu3EZ0Pgg93K2SVNLCjCSvE.jpg'
        },
        {
            'title': 'Wednesday',
            'type': 'tv',
            'genre': 'comedy',
            'year': 2022,
            'rating': 8.1,
            'director': 'Alfred Gough',
            'cast': ['Jenna Ortega', 'Hunter Doohan', 'Percy Hynes White'],
            'runtime': 45,
            'seasons': 1,
            'episodes': 8,
            'description': 'Follows Wednesday Addams\' years as a student at Nevermore Academy, where she tries to master her emerging psychic ability.',
            'poster': 'https://image.tmdb.org/t/p/w500/9PFonBhy4cQy7Jz20NpMygczOkv.jpg'
        },
        {
            'title': 'House of the Dragon',
            'type': 'tv',
            'genre': 'fantasy',
            'year': 2022,
            'rating': 8.5,
            'director': 'Ryan Condal',
            'cast': ['Paddy Considine', 'Emma D\'Arcy', 'Matt Smith'],
            'runtime': 60,
            'seasons': 1,
            'episodes': 10,
            'description': 'An internal succession war within House Targaryen at the height of its power, 172 years before the birth of Daenerys.',
            'poster': 'https://image.tmdb.org/t/p/w500/z2yahl2uefxDCl0nogcRBstwruJ.jpg'
        }
    ]
    
    # Filter content based on criteria
    filtered_content = []
    min_rating = float(rating) if rating != 'any' and rating else 0.0
    min_year = int(year) if year != 'any' and year != 'recent' else 0
    
    for content in content_database:
        genre_match = (genre == 'any' or content['genre'] == genre)
        type_match = (content_type == 'any' or content['type'] == content_type)
        
        # Year filtering
        if year == 'recent':
            year_match = content['year'] >= 2020
        elif year == 'classic':
            year_match = content['year'] <= 2000
        else:
            year_match = (year == 'any' or content['year'] >= min_year)
        
        rating_match = (rating == 'any' or content['rating'] >= min_rating)
        
        if genre_match and type_match and year_match and rating_match:
            filtered_content.append(content)
    
    return filtered_content

def format_tmdb_response(content, content_type):
    """Format content data to match TMDB API response structure"""
    
    # Calculate content details
    if content_type == 'tv':
        duration_info = f"{content.get('seasons', 1)} Season{'s' if content.get('seasons', 1) > 1 else ''}, {content.get('episodes', 'Unknown')} Episodes"
        runtime_info = f"~{content.get('runtime', 45)} min/episode"
    else:
        duration_info = f"{content.get('runtime', 120)} minutes"
        runtime_info = duration_info
    
    formatted_response = {
        'title': content['title'],
        'type': content['type'],
        'genre': content['genre'],
        'year': content['year'],
        'rating': content['rating'],
        'director': content['director'],
        'cast': content['cast'][:3],  # Top 3 cast members
        'duration': duration_info,
        'runtime': runtime_info,
        'description': content['description'],
        'poster_url': content.get('poster', ''),
        'source': 'TMDB API Simulation',
        'additional_info': {
            'seasons': content.get('seasons') if content['type'] == 'tv' else None,
            'episodes': content.get('episodes') if content['type'] == 'tv' else None,
            'budget': content.get('budget') if content['type'] == 'movie' else None,
            'box_office': content.get('box_office') if content['type'] == 'movie' else None
        }
    }
    
    return formatted_response

def fetch_from_omdb_api(genre, content_type, year, rating):
    """Fetch from OMDB API as backup"""
    try:
        # OMDB API simulation - in production you'd use actual API calls
        # For now, we'll use our curated database with OMDB-style formatting
        
        popular_content = get_popular_content_by_filters(genre, content_type, year, rating)
        
        if popular_content:
            selected = random.choice(popular_content)
            return format_omdb_response(selected)
        
        raise Exception('No content found from OMDB simulation')
        
    except Exception as e:
        raise Exception(f'OMDB API error: {str(e)}')

def format_omdb_response(content):
    """Format content data to match OMDB API response structure"""
    
    content_type = 'series' if content['type'] == 'tv' else 'movie'
    
    formatted_response = {
        'title': content['title'],
        'type': content['type'],
        'genre': content['genre'],
        'year': content['year'],
        'rating': content['rating'],
        'director': content['director'],
        'cast': ', '.join(content['cast'][:3]),
        'duration': f"{content.get('runtime', 120)} min" if content['type'] == 'movie' else f"{content.get('seasons', 1)} seasons",
        'runtime': f"{content.get('runtime', 120)} min",
        'description': content['description'],
        'poster_url': content.get('poster', ''),
        'source': 'OMDB API Simulation',
        'imdb_rating': str(content['rating']),
        'content_type': content_type
    }
    
    return formatted_response

def fetch_movie_reddit_recommendations(genre, content_type):
    """Enhanced Reddit fetching for movies and TV shows"""
    try:
        # Choose subreddit based on content type
        subreddit_mapping = {
            'movie': ['movies', 'MovieSuggestions', 'flicks', 'cinema'],
            'tv': ['television', 'televisionsuggestions', 'AskReddit'],
            'any': ['movies', 'television', 'MovieSuggestions', 'AskReddit']
        }
        
        subreddits = subreddit_mapping.get(content_type, ['movies', 'television'])
        selected_subreddit = random.choice(subreddits)
        
        headers = {
            'User-Agent': 'Django-Movie-Finder/1.0'
        }
        
        # Build search query
        search_terms = ['recommend', 'suggestion', 'best', 'watch']
        if genre != 'any':
            search_terms.append(genre)
        if content_type != 'any':
            search_terms.append(content_type)
            
        search_query = ' OR '.join(search_terms)
        url = f'https://www.reddit.com/r/{selected_subreddit}/search.json?q={quote(search_query)}&limit=50&sort=top&t=month'
        
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code != 200:
            raise Exception(f'Reddit API returned status {response.status_code}')
        
        data = response.json()
        posts = data['data']['children']
        
        # Extract movie/TV recommendations
        recommendations = extract_movie_recommendations(posts, genre, content_type)
        
        if recommendations:
            return random.choice(recommendations)
        
        raise Exception('No recommendations found in Reddit')
        
    except Exception as e:
        raise Exception(f'Reddit API error: {str(e)}')

def extract_movie_recommendations(posts, genre, content_type):
    """Extract movie/TV recommendations from Reddit posts"""
    recommendations = []
    
    # Popular titles database for recognition
    popular_titles = {
        # Movies
        'The Dark Knight': {'type': 'movie', 'genre': 'action', 'year': 2008, 'rating': 9.0},
        'Inception': {'type': 'movie', 'genre': 'sci-fi', 'year': 2010, 'rating': 8.8},
        'Parasite': {'type': 'movie', 'genre': 'thriller', 'year': 2019, 'rating': 8.6},
        'The Godfather': {'type': 'movie', 'genre': 'crime', 'year': 1972, 'rating': 9.2},
        'Pulp Fiction': {'type': 'movie', 'genre': 'crime', 'year': 1994, 'rating': 8.9},
        'Interstellar': {'type': 'movie', 'genre': 'sci-fi', 'year': 2014, 'rating': 8.6},
        'The Shawshank Redemption': {'type': 'movie', 'genre': 'drama', 'year': 1994, 'rating': 9.3},
        
        # TV Shows
        'Breaking Bad': {'type': 'tv', 'genre': 'crime', 'year': 2008, 'rating': 9.5},
        'Game of Thrones': {'type': 'tv', 'genre': 'fantasy', 'year': 2011, 'rating': 8.7},
        'Stranger Things': {'type': 'tv', 'genre': 'sci-fi', 'year': 2016, 'rating': 8.7},
        'The Office': {'type': 'tv', 'genre': 'comedy', 'year': 2005, 'rating': 8.9},
        'Friends': {'type': 'tv', 'genre': 'comedy', 'year': 1994, 'rating': 8.9},
        'The Crown': {'type': 'tv', 'genre': 'drama', 'year': 2016, 'rating': 8.7}
    }
    
    for post in posts:
        post_data = post['data']
        title_text = post_data.get('title', '').lower()
        selftext = post_data.get('selftext', '').lower()
        combined_text = f"{title_text} {selftext}"
        
        # Look for titles in the text
        for known_title, metadata in popular_titles.items():
            if known_title.lower() in combined_text:
                # Check if it matches our filters
                if (content_type == 'any' or metadata['type'] == content_type) and \
                   (genre == 'any' or metadata['genre'] == genre):
                    
                    # Generate full recommendation
                    rec = generate_movie_recommendation(known_title, metadata)
                    if rec:
                        recommendations.append(rec)
                        break  # Only add one per post
    
    return recommendations

def generate_movie_recommendation(title, metadata):
    """Generate a full movie/TV recommendation from title and metadata"""
    
    # Extended database with full information
    full_database = {
        'The Dark Knight': {
            'director': 'Christopher Nolan', 'cast': ['Christian Bale', 'Heath Ledger', 'Aaron Eckhart'],
            'description': 'When the menace known as the Joker wreaks havoc and chaos on the people of Gotham, Batman must accept one of the greatest psychological and physical tests.',
            'runtime': 152
        },
        'Breaking Bad': {
            'director': 'Vince Gilligan', 'cast': ['Bryan Cranston', 'Aaron Paul', 'Anna Gunn'],
            'description': 'A high school chemistry teacher diagnosed with inoperable lung cancer turns to manufacturing and selling methamphetamine.',
            'seasons': 5, 'episodes': 62
        }
        # Add more as needed
    }
    
    if title in full_database:
        full_info = full_database[title]
        
        # Format duration based on type
        if metadata['type'] == 'tv':
            duration = f"{full_info.get('seasons', 1)} Season{'s' if full_info.get('seasons', 1) > 1 else ''}"
            runtime = f"~{full_info.get('runtime', 45)} min/episode"
        else:
            duration = f"{full_info.get('runtime', 120)} minutes"
            runtime = duration
        
        return {
            'title': title,
            'type': metadata['type'],
            'genre': metadata['genre'],
            'year': metadata['year'],
            'rating': metadata['rating'],
            'director': full_info['director'],
            'cast': full_info['cast'][:3],
            'duration': duration,
            'runtime': runtime,
            'description': full_info['description'],
            'source': 'Enhanced Reddit API'
        }
    
    return None

def get_curated_movie_recommendation(genre, content_type, year, rating):
    """Enhanced fallback to our curated movie/TV database"""
    
    # Use the comprehensive database from get_popular_content_by_filters
    content_list = get_popular_content_by_filters(genre, content_type, year, rating)
    
    if content_list:
        selected = random.choice(content_list)
        return format_tmdb_response(selected, selected['type'])
    else:
        # If no matches, return a popular title
        fallback_content = get_popular_content_by_filters('any', content_type, 'any', 'any')
        if fallback_content:
            selected = random.choice(fallback_content)
            return format_tmdb_response(selected, selected['type'])
        else:
            # Ultimate fallback
            return {
                'title': 'The Shawshank Redemption',
                'type': 'movie',
                'genre': 'drama',
                'year': 1994,
                'rating': 9.3,
                'director': 'Frank Darabont',
                'cast': ['Tim Robbins', 'Morgan Freeman', 'Bob Gunton'],
                'duration': '142 minutes',
                'runtime': '142 minutes',
                'description': 'Two imprisoned men bond over a number of years, finding solace and eventual redemption through acts of common decency.',
                'source': 'Curated Database'
            }

def clean_description(description):
    """Clean HTML tags and excessive text from descriptions"""
    if not description:
        return "No description available."
    
    # Remove HTML tags
    import re
    clean_desc = re.sub('<.*?>', '', description)
    
    # Limit length
    if len(clean_desc) > 300:
        clean_desc = clean_desc[:297] + "..."
    
    return clean_desc
