import discord
import aiohttp
import asyncio
import sqlite3
import os
import re
import json
from datetime import datetime, timedelta
from discord.ext import commands, tasks
from dotenv import load_dotenv

# ========== CONFIGURAÇÃO ==========
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

if not TOKEN:
    print("❌ DISCORD_TOKEN não encontrado no .env")
    exit(1)

# ========== BANCO DE DADOS CORRIGIDO ==========
class YouTubeDB:
    def __init__(self):
        self.conn = sqlite3.connect('youtube_bot_v3.db', check_same_thread=False)
        self.create_tables()
        print("✅ Banco de dados V3 pronto")
    
    def create_tables(self):
        c = self.conn.cursor()
        
        # Configurações do servidor (MELHORADA)
        c.execute('''
            CREATE TABLE IF NOT EXISTS configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                server_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                youtube_url TEXT NOT NULL,
                youtube_name TEXT NOT NULL,
                youtube_id TEXT,
                last_video TEXT DEFAULT '',
                last_video_title TEXT DEFAULT '',
                last_video_time TEXT DEFAULT '',
                last_live TEXT DEFAULT '',
                last_live_title TEXT DEFAULT '',
                scheduled_live TEXT DEFAULT '',
                scheduled_live_time TEXT DEFAULT '',
                notify_videos INTEGER DEFAULT 1,
                notify_lives INTEGER DEFAULT 1,
                notify_scheduled INTEGER DEFAULT 1,
                config_user TEXT,
                created TEXT,
                last_check TEXT,
                is_active INTEGER DEFAULT 1,
                UNIQUE(server_id, youtube_id)
            )
        ''')
        
        # Histórico de notificações
        c.execute('''
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                server_id TEXT NOT NULL,
                youtube_id TEXT NOT NULL,
                video_id TEXT NOT NULL,
                video_title TEXT NOT NULL,
                video_type TEXT NOT NULL,
                notified_at TEXT NOT NULL,
                channel_name TEXT NOT NULL
            )
        ''')
        
        # Índices para melhor performance
        c.execute('CREATE INDEX IF NOT EXISTS idx_configs_server ON configs(server_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_configs_active ON configs(is_active)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_history_server ON history(server_id)')
        
        self.conn.commit()
    
    def save_config(self, server_id, channel_id, youtube_url, youtube_name, youtube_id, user_id):
        c = self.conn.cursor()
        
        # Verifica se já existe configuração para este canal neste servidor
        c.execute('''
            SELECT id FROM configs 
            WHERE server_id = ? AND youtube_id = ? AND is_active = 1
        ''', (str(server_id), youtube_id))
        
        existing = c.fetchone()
        
        if existing:
            # Atualiza configuração existente
            c.execute('''
                UPDATE configs 
                SET channel_id = ?, youtube_url = ?, youtube_name = ?, 
                    last_check = ?, config_user = ?
                WHERE id = ?
            ''', (str(channel_id), youtube_url, youtube_name, 
                  datetime.now().isoformat(), str(user_id), existing[0]))
        else:
            # Insere nova configuração
            c.execute('''
                INSERT INTO configs 
                (server_id, channel_id, youtube_url, youtube_name, youtube_id, 
                 config_user, created, last_check, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            ''', (str(server_id), str(channel_id), youtube_url, youtube_name, 
                  youtube_id, str(user_id), datetime.now().isoformat(), 
                  datetime.now().isoformat()))
        
        self.conn.commit()
        return True
    
    def get_config(self, server_id, youtube_id=None):
        c = self.conn.cursor()
        
        if youtube_id:
            c.execute('''
                SELECT * FROM configs 
                WHERE server_id = ? AND youtube_id = ? AND is_active = 1
            ''', (str(server_id), youtube_id))
        else:
            # Retorna TODAS as configurações do servidor
            c.execute('''
                SELECT * FROM configs 
                WHERE server_id = ? AND is_active = 1
                ORDER BY created DESC
            ''', (str(server_id),))
        
        return c.fetchall()
    
    def get_all_configs(self):
        """Retorna TODAS as configurações ativas de TODOS os servidores"""
        c = self.conn.cursor()
        c.execute('''
            SELECT * FROM configs 
            WHERE is_active = 1
            ORDER BY server_id, created DESC
        ''')
        return c.fetchall()
    
    def get_active_configs(self):
        """Pega apenas configs que têm notificações ativas"""
        c = self.conn.cursor()
        c.execute('''
            SELECT * FROM configs 
            WHERE is_active = 1 
            AND (notify_videos = 1 OR notify_lives = 1 OR notify_scheduled = 1)
            ORDER BY server_id, created DESC
        ''')
        return c.fetchall()
    
    def get_server_configs_count(self, server_id):
        """Conta quantos canais um servidor está monitorando"""
        c = self.conn.cursor()
        c.execute('''
            SELECT COUNT(*) FROM configs 
            WHERE server_id = ? AND is_active = 1
        ''', (str(server_id),))
        return c.fetchone()[0]
    
    def update_video(self, server_id, youtube_id, video_id, title, publish_time):
        c = self.conn.cursor()
        c.execute('''
            UPDATE configs 
            SET last_video = ?, last_video_title = ?, last_video_time = ?, last_check = ?
            WHERE server_id = ? AND youtube_id = ? AND is_active = 1
        ''', (video_id, title, publish_time, datetime.now().isoformat(), 
              str(server_id), youtube_id))
        self.conn.commit()
    
    def update_live(self, server_id, youtube_id, video_id, title):
        c = self.conn.cursor()
        c.execute('''
            UPDATE configs 
            SET last_live = ?, last_live_title = ?, last_check = ?
            WHERE server_id = ? AND youtube_id = ? AND is_active = 1
        ''', (video_id, title, datetime.now().isoformat(), 
              str(server_id), youtube_id))
        self.conn.commit()
    
    def update_scheduled(self, server_id, youtube_id, video_id, title, scheduled_time):
        c = self.conn.cursor()
        c.execute('''
            UPDATE configs 
            SET scheduled_live = ?, scheduled_live_time = ?, last_check = ?
            WHERE server_id = ? AND youtube_id = ? AND is_active = 1
        ''', (video_id, title, scheduled_time, datetime.now().isoformat(), 
              str(server_id), youtube_id))
        self.conn.commit()
    
    def add_history(self, server_id, youtube_id, video_id, title, video_type, channel_name):
        c = self.conn.cursor()
        c.execute('''
            INSERT INTO history 
            (server_id, youtube_id, video_id, video_title, video_type, notified_at, channel_name)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (str(server_id), youtube_id, video_id, title, video_type, 
              datetime.now().isoformat(), channel_name))
        self.conn.commit()
    
    def get_history(self, server_id, limit=10):
        c = self.conn.cursor()
        c.execute('''
            SELECT * FROM history 
            WHERE server_id = ? 
            ORDER BY notified_at DESC 
            LIMIT ?
        ''', (str(server_id), limit))
        return c.fetchall()
    
    def update_setting(self, server_id, youtube_id, setting, value):
        c = self.conn.cursor()
        c.execute(f'''
            UPDATE configs 
            SET {setting} = ?, last_check = ?
            WHERE server_id = ? AND youtube_id = ? AND is_active = 1
        ''', (value, datetime.now().isoformat(), str(server_id), youtube_id))
        self.conn.commit()
    
    def delete_config(self, server_id, youtube_id=None):
        c = self.conn.cursor()
        
        if youtube_id:
            # Remove configuração específica
            c.execute('''
                UPDATE configs 
                SET is_active = 0 
                WHERE server_id = ? AND youtube_id = ?
            ''', (str(server_id), youtube_id))
            deleted = c.rowcount > 0
            
            # Remove histórico específico
            c.execute('DELETE FROM history WHERE server_id = ? AND youtube_id = ?', 
                     (str(server_id), youtube_id))
        else:
            # Remove TODAS as configurações do servidor
            c.execute('''
                UPDATE configs 
                SET is_active = 0 
                WHERE server_id = ?
            ''', (str(server_id),))
            deleted = c.rowcount > 0
            
            # Remove TODO o histórico do servidor
            c.execute('DELETE FROM history WHERE server_id = ?', (str(server_id),))
        
        self.conn.commit()
        return deleted

# ========== BOT ==========
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)
db = YouTubeDB()

# ========== FUNÇÕES YOUTUBE ==========
async def fetch_youtube_data(url):
    """Busca dados do YouTube"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept-Language': 'pt-BR,pt;q=0.9,en;q=0.8',
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=10) as response:
                if response.status == 200:
                    return await response.text()
    except Exception as e:
        print(f"Erro ao buscar {url}: {e}")
    
    return None

async def extract_youtube_info(url):
    """Extrai informações do canal - VERSÃO 2024 OTIMIZADA"""
    html = await fetch_youtube_data(url)
    if not html:
        print(f"❌ Não foi possível obter HTML de {url}")
        return None
    
    info = {
        'channel_name': 'Canal do YouTube',
        'channel_id': None,
        'is_live': False,
        'live_info': None,
        'scheduled_live': None,
        'latest_video': None,
        'recent_videos': [],
        'channel_url': url
    }
    
    try:
        print(f"🔍 Analisando HTML de {url}...")
        
        # ========== MÉTODO 1: Busca por JSON ytInitialData ==========
        # O YouTube armazena dados em um JSON gigante chamado ytInitialData
        initial_data_match = re.search(r'var ytInitialData\s*=\s*({.*?});', html, re.DOTALL)
        
        if initial_data_match:
            try:
                print("📊 Tentando extrair via JSON ytInitialData...")
                data = json.loads(initial_data_match.group(1))
                
                # Função para buscar informações recursivamente no JSON
                def search_in_json(obj, path=""):
                    if isinstance(obj, dict):
                        # Procura por nome do canal
                        if 'title' in obj:
                            title_data = obj['title']
                            if 'runs' in title_data and title_data['runs']:
                                runs = title_data['runs']
                                for run in runs:
                                    if 'text' in run:
                                        info['channel_name'] = run['text']
                                        break
                            elif 'simpleText' in title_data:
                                info['channel_name'] = title_data['simpleText']
                        
                        # Procura por ID do canal
                        if 'channelId' in obj:
                            info['channel_id'] = obj['channelId']
                        elif 'browseId' in obj and 'UC' in str(obj['browseId']):
                            info['channel_id'] = obj['browseId']
                        
                        # Procura por live
                        if obj.get('isLive') is True or obj.get('style') == 'LIVE':
                            info['is_live'] = True
                            if 'videoId' in obj:
                                video_id = obj['videoId']
                                title = obj.get('title', {})
                                title_text = ""
                                
                                if 'runs' in title and title['runs']:
                                    title_text = title['runs'][0].get('text', '')
                                elif 'simpleText' in title:
                                    title_text = title['simpleText']
                                
                                info['live_info'] = {
                                    'id': video_id,
                                    'title': title_text,
                                    'url': f"https://youtu.be/{video_id}",
                                    'thumbnail': f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg",
                                    'type': 'live'
                                }
                        
                        # Procura por vídeos
                        if 'videoId' in obj and 'title' in obj:
                            video_id = obj['videoId']
                            title_data = obj['title']
                            title_text = ""
                            
                            if 'runs' in title_data and title_data['runs']:
                                title_text = title_data['runs'][0].get('text', '')
                            elif 'simpleText' in title_data:
                                title_text = title_data['simpleText']
                            
                            # É o primeiro vídeo encontrado?
                            if not info['latest_video']:
                                info['latest_video'] = {
                                    'id': video_id,
                                    'title': title_text,
                                    'thumbnail': f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg",
                                    'url': f"https://youtu.be/{video_id}",
                                    'publish_time': 'Recentemente',
                                    'type': 'video'
                                }
                            
                            # Adiciona à lista de vídeos recentes
                            info['recent_videos'].append({
                                'id': video_id,
                                'title': title_text,
                                'thumbnail': f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg",
                                'url': f"https://youtu.be/{video_id}",
                                'publish_time': 'Recentemente',
                                'type': 'video'
                            })
                        
                        # Busca recursivamente
                        for key, value in obj.items():
                            if key not in ['thumbnail', 'avatar', 'image']:  # Pula grandes objetos
                                search_in_json(value, f"{path}.{key}")
                    
                    elif isinstance(obj, list):
                        for item in obj:
                            search_in_json(item, path)
                
                # Executa a busca
                search_in_json(data)
                print(f"✅ JSON analisado: {info['channel_name']} (ID: {info['channel_id']})")
                
            except json.JSONDecodeError as e:
                print(f"⚠️ Erro ao decodificar JSON: {e}")
            except Exception as e:
                print(f"⚠️ Erro no método JSON: {e}")
        
        # ========== MÉTODO 2: Regex modernas para 2024 ==========
        # Se o JSON não funcionou, usa regex atualizadas
        
        # 1. Extrai nome do canal (múltiplas tentativas)
        name_patterns = [
            r'<meta property="og:title" content="([^"]+)"',
            r'<meta name="title" content="([^"]+)"',
            r'<title>([^<]+) - YouTube</title>',
            r'"author":"([^"]+)"',
            r'"channelName":"([^"]+)"',
            r'"title":"([^"]+)"[^}]*"canonicalBaseUrl":"/@[^"]+"',
            r'"header":"c4TabbedHeaderRenderer"[^}]+"title":"([^"]+)"',
        ]
        
        for pattern in name_patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                name = match.group(1).strip()
                if name and len(name) > 2 and 'YouTube' not in name:
                    info['channel_name'] = name.replace(' - YouTube', '').replace('\\"', '"')
                    print(f"✅ Nome encontrado via regex: {info['channel_name']}")
                    break
        
        # 2. Extrai ID do canal (múltiplas tentativas)
        id_patterns = [
            r'"channelId":"([^"]+)"',
            r'"browseId":"([^"]+)"',
            r'<link rel="canonical" href="https://www\.youtube\.com/channel/([^"]+)"',
            r'"externalId":"([^"]+)"',
            r'data-channel-external-id="([^"]+)"',
        ]
        
        for pattern in id_patterns:
            match = re.search(pattern, html)
            if match:
                channel_id = match.group(1)
                if channel_id and ('UC' in channel_id or channel_id.startswith('@')):
                    info['channel_id'] = channel_id
                    print(f"✅ ID encontrado via regex: {info['channel_id']}")
                    break
        
        # Se não encontrou ID ainda, tenta extrair da URL
        if not info['channel_id']:
            if '/channel/' in url:
                match = re.search(r'/channel/([^/?]+)', url)
                if match:
                    info['channel_id'] = match.group(1)
            elif '/@' in url:
                match = re.search(r'/@([^/?]+)', url)
                if match:
                    info['channel_id'] = '@' + match.group(1)
            elif '/c/' in url:
                match = re.search(r'/c/([^/?]+)', url)
                if match:
                    info['channel_id'] = 'c_' + match.group(1)
        
        # 3. Verifica se está em live (padrões modernos)
        live_patterns = [
            r'"isLive":true',
            r'"isLiveBroadcast":true',
            r'"style":"LIVE"',
            r'"badges":\[[^\]]*"live"[^\]]*\]',
            r'<span[^>]*aria-label="[^"]*AO VIVO[^"]*"',
            r'<span[^>]*class="[^"]*badge-style-type-live[^"]*"',
            r'<link[^>]*content="https://www\.youtube\.com/watch\?v=[^"]*"[^>]*type="application/x\+youtube-live-message"',
        ]
        
        for pattern in live_patterns:
            if re.search(pattern, html, re.IGNORECASE):
                info['is_live'] = True
                print("🎬 Live detectada!")
                break
        
        # 4. Extrai informações da live (se houver)
        if info['is_live']:
            # Padrões modernos para live
            live_info_patterns = [
                r'"videoId":"([^"]+)"[^}]*"title":\{"runs":\[\{"text":"([^"]+)"',
                r'"videoId":"([^"]+)"[^}]*"title":\{"simpleText":"([^"]+)"',
                r'watch\?v=([^"&]+)[^>]*title="([^"]+)"[^>]*aria-label="[^"]*AO VIVO',
                r'<meta property="og:title" content="([^"]+)[^"]*AO VIVO[^"]*"[^>]*>\s*<meta property="og:url" content="[^"]*v=([^"&]+)"',
            ]
            
            for pattern in live_info_patterns:
                match = re.search(pattern, html, re.IGNORECASE)
                if match:
                    video_id = match.group(1)
                    title = match.group(2).replace('\\"', '"')
                    info['live_info'] = {
                        'id': video_id,
                        'title': title,
                        'url': f"https://youtu.be/{video_id}",
                        'thumbnail': f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg",
                        'type': 'live'
                    }
                    print(f"✅ Informações da live: {title}")
                    break
        
        # 5. Extrai vídeos recentes
        video_patterns = [
            r'"videoId":"([^"]+)"[^}]*"title":\{"runs":\[\{"text":"([^"]+)"[^}]*"thumbnail":\{"thumbnails":\[\{"url":"([^"]+)"',
            r'"videoId":"([^"]+)"[^}]*"title":\{"simpleText":"([^"]+)"[^}]*"thumbnail":\{"thumbnails":\[\{"url":"([^"]+)"',
            r'<a[^>]*href="/watch\?v=([^"&]+)"[^>]*title="([^"]+)"[^>]*><img[^>]*src="([^"]+)"',
            r'ytInitialData["\'][^}]+"videoId":"([^"]+)"[^}]+"title":\{[^}]+\}[^}]+"thumbnail":\{[^}]+\}[^}]+"publishedTimeText":\{[^}]+\}[^}]+"simpleText":"([^"]+)"',
        ]
        
        for pattern in video_patterns:
            matches = re.findall(pattern, html, re.IGNORECASE)
            if matches:
                print(f"📹 Encontrados {len(matches)} vídeos via regex")
                for i, match in enumerate(matches[:5]):  # Limita a 5 vídeos
                    video_id = match[0]
                    title = match[1].replace('\\"', '"') if len(match) > 1 else "Vídeo recente"
                    thumbnail = match[2].replace('\\u0026', '&') if len(match) > 2 else f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"
                    
                    video_info = {
                        'id': video_id,
                        'title': title[:100] + "..." if len(title) > 100 else title,
                        'thumbnail': thumbnail,
                        'url': f"https://youtu.be/{video_id}",
                        'publish_time': match[3] if len(match) > 3 else 'Recentemente',
                        'type': 'video'
                    }
                    
                    if i == 0:  # Primeiro vídeo é o mais recente
                        info['latest_video'] = video_info
                    
                    info['recent_videos'].append(video_info)
                break
        
        # 6. Se não encontrou vídeos ainda, tenta padrão mais simples
        if not info['latest_video']:
            simple_video_pattern = r'watch\?v=([^"&]+)'
            video_matches = re.findall(simple_video_pattern, html)
            if video_matches:
                video_id = video_matches[0]  # Primeiro vídeo encontrado
                info['latest_video'] = {
                    'id': video_id,
                    'title': 'Vídeo recente',
                    'thumbnail': f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg",
                    'url': f"https://youtu.be/{video_id}",
                    'publish_time': 'Recentemente',
                    'type': 'video'
                }
                print(f"✅ Vídeo encontrado via padrão simples: {video_id}")
        
        # ========== VALIDAÇÃO FINAL ==========
        # Se não conseguiu ID do canal, cria um baseado no nome
        if not info['channel_id']:
            # Cria um ID fictício baseado no nome (para funcionar no banco)
            clean_name = re.sub(r'[^a-zA-Z0-9]', '', info['channel_name'])
            info['channel_id'] = f"custom_{clean_name[:20]}" if clean_name else f"custom_{hash(url) % 10000}"
            print(f"⚠️ Usando ID customizado: {info['channel_id']}")
        
        print(f"✅ Análise concluída: {info['channel_name']}")
        return info
        
    except Exception as e:
        print(f"❌ Erro crítico ao processar {url}: {e}")
        import traceback
        traceback.print_exc()
    
    return info

# ========== SISTEMA DE COMANDOS MULTI-CANAL ==========
class YouTubeCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @commands.command(name='yt')
    async def setup_youtube(self, ctx, *, youtube_url=None):
        """🎬 Configura monitoramento de canal"""
        
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("❌ **Apenas administradores podem configurar.**")
            return
        
        # Pega TODOS os canais configurados neste servidor
        configs = db.get_config(ctx.guild.id)
        
        if not youtube_url:
            if configs:
                await self.show_all_configs(ctx, configs)
            else:
                await self.show_setup_guide(ctx)
            return
        
        await self.process_configuration(ctx, youtube_url)
    
    async def show_all_configs(self, ctx, configs):
        """Mostra TODOS os canais configurados no servidor"""
        embed = discord.Embed(
            title=f"📺 **{len(configs)} Canal(es) Monitorado(s)**",
            description=f"**Servidor:** {ctx.guild.name}",
            color=0x7289DA
        )
        
        for config in configs:
            # Desempacota a configuração
            config_id, server_id, channel_id, youtube_url, youtube_name, youtube_id, \
            last_video, last_video_title, last_video_time, last_live, last_live_title, \
            scheduled_live, scheduled_live_time, notify_videos, notify_lives, \
            notify_scheduled, config_user, created, last_check, is_active = config
            
            # Status das notificações
            notify_status = []
            if notify_videos: notify_status.append("📹")
            if notify_lives: notify_status.append("🎬")
            if notify_scheduled: notify_status.append("📅")
            
            embed.add_field(
                name=f"**{youtube_name}**",
                value=f"**ID:** `{youtube_id or 'N/A'}`\n"
                      f"**Notificar:** {' '.join(notify_status) if notify_status else '❌'}\n"
                      f"**Configurado:** {created[:10]}\n"
                      f"**Comandos:** `!yt_info {youtube_id or 'ID'}`",
                inline=True
            )
        
        embed.add_field(
            name="🔧 **Gerenciar Canais**",
            value="```css\n"
                  "!yt_info [ID]     - Ver detalhes de um canal\n"
                  "!yt_remove [ID]   - Remover um canal\n"
                  "!yt_all           - Ver esta lista novamente\n"
                  "```",
            inline=False
        )
        
        embed.set_footer(text=f"Total: {len(configs)} canal(es) • Use !yt <link> para adicionar mais")
        await ctx.send(embed=embed)
    
    async def show_setup_guide(self, ctx):
        """Mostra guia de configuração"""
        embed = discord.Embed(
            title="🎬 **Configurar Monitor YouTube**",
            description="**Você pode monitorar MÚLTIPLOS canais!**\n\n"
                       "**Como adicionar:**\n"
                       "`!yt https://youtube.com/@canal1`\n"
                       "`!yt https://youtube.com/@canal2`\n"
                       "`!yt https://youtube.com/@canal3`\n\n"
                       "**Todos serão monitorados simultaneamente!**",
            color=0xFF0000
        )
        
        embed.add_field(
            name="⚡ **Recursos Multi-Canal:**",
            value="✅ **Múltiplos canais por servidor**\n"
                  "✅ **Monitoramento simultâneo**\n"
                  "✅ **Configurações individuais por canal**\n"
                  "✅ **Histórico separado por canal**",
            inline=False
        )
        
        await ctx.send(embed=embed)
    
    async def process_configuration(self, ctx, youtube_url):
        """Processa a configuração de um novo canal"""
        try:
            # Formata URL
            if youtube_url.startswith('@'):
                youtube_url = f"https://youtube.com/{youtube_url}"
            elif not youtube_url.startswith('http'):
                youtube_url = f"https://youtube.com/@{youtube_url}"
            
            processing_msg = await ctx.send("🔍 **Analisando canal...**")
            
            # Extrai informações
            info = await extract_youtube_info(youtube_url)
            
            if not info or not info['channel_id']:
                await processing_msg.edit(content="❌ **Canal não encontrado.** Verifique o link.")
                return
            
            # Verifica se já está monitorando este canal neste servidor
            existing_configs = db.get_config(ctx.guild.id, info['channel_id'])
            
            if existing_configs:
                await processing_msg.edit(content=f"✅ **{info['channel_name']} já está sendo monitorado neste servidor!**")
                return
            
            # Salva configuração
            db.save_config(
                ctx.guild.id,
                ctx.channel.id,
                info['channel_url'],
                info['channel_name'],
                info['channel_id'],
                ctx.author.id
            )
            
            # Conta quantos canais o servidor está monitorando agora
            total_canais = db.get_server_configs_count(ctx.guild.id)
            
            # Cria embed de sucesso
            embed = discord.Embed(
                title="✅ **Canal Adicionado!**",
                description=f"**{info['channel_name']}** foi adicionado ao monitoramento.",
                color=0x00FF00
            )
            
            embed.add_field(
                name="📊 **Status do Servidor:**",
                value=f"**Canais monitorados:** {total_canais}\n"
                      f"**Notificações em:** <#{ctx.channel.id}>",
                inline=False
            )
            
            if info['is_live'] and info['live_info']:
                embed.add_field(
                    name="🎬 **LIVE DETECTADA!**",
                    value=f"**{info['live_info']['title']}**\n[Assistir]({info['live_info']['url']})",
                    inline=False
                )
                embed.set_image(url=info['live_info']['thumbnail'])
            
            if info['latest_video']:
                embed.add_field(
                    name="📹 **ÚLTIMO VÍDEO**",
                    value=f"**{info['latest_video']['title'][:60]}...**\n"
                          f"⏰ {info['latest_video']['publish_time']}",
                    inline=False
                )
                if not info['is_live']:
                    embed.set_thumbnail(url=info['latest_video']['thumbnail'])
            
            embed.add_field(
                name="🔧 **Gerenciar Canais:**",
                value="Use `!yt` para ver todos os canais\n"
                      "Use `!yt_info {ID}` para ver detalhes",
                inline=False
            )
            
            embed.set_footer(text=f"Adicionado por {ctx.author.name} • Total: {total_canais} canal(es)")
            await processing_msg.edit(content=None, embed=embed)
            
        except Exception as e:
            print(f"Erro na configuração: {e}")
            await ctx.send("❌ **Erro na configuração.** Tente novamente.")
    
    @commands.command(name='yt_info')
    async def show_channel_info(self, ctx, identifier=None):
        """📋 Mostra informações detalhadas de um canal"""
        configs = db.get_config(ctx.guild.id)
        
        if not configs:
            await ctx.send("❌ **Nenhum canal configurado.** Use `!yt` primeiro.")
            return
        
        if not identifier:
            # Mostra lista de canais para escolher
            embed = discord.Embed(
                title="📋 **Selecione um Canal**",
                description="**Use um dos comandos abaixo:**",
                color=0x7289DA
            )
            
            for config in configs:
                config_id, server_id, channel_id, youtube_url, youtube_name, youtube_id, \
                last_video, last_video_title, last_video_time, last_live, last_live_title, \
                scheduled_live, scheduled_live_time, notify_videos, notify_lives, \
                notify_scheduled, config_user, created, last_check, is_active = config
                
                embed.add_field(
                    name=f"**{youtube_name}**",
                    value=f"`!yt_info {youtube_id[:8]}...`",
                    inline=True
                )
            
            await ctx.send(embed=embed)
            return
        
        # Procura o canal pelo ID ou nome
        target_config = None
        for config in configs:
            config_id, server_id, channel_id, youtube_url, youtube_name, youtube_id, \
            last_video, last_video_title, last_video_time, last_live, last_live_title, \
            scheduled_live, scheduled_live_time, notify_videos, notify_lives, \
            notify_scheduled, config_user, created, last_check, is_active = config
            
            if youtube_id and identifier in youtube_id:
                target_config = config
                break
            elif identifier.lower() in youtube_name.lower():
                target_config = config
                break
        
        if not target_config:
            await ctx.send("❌ **Canal não encontrado.** Use `!yt` para ver a lista.")
            return
        
        # Desempacota a configuração
        config_id, server_id, channel_id, youtube_url, youtube_name, youtube_id, \
        last_video, last_video_title, last_video_time, last_live, last_live_title, \
        scheduled_live, scheduled_live_time, notify_videos, notify_lives, \
        notify_scheduled, config_user, created, last_check, is_active = target_config
        
        processing_msg = await ctx.send("🔍 **Buscando informações atualizadas...**")
        
        try:
            # Busca informações atualizadas
            info = await extract_youtube_info(youtube_url)
            
            embed = discord.Embed(
                title=f"📺 **{youtube_name}**",
                description=f"**ID:** `{youtube_id}`\n"
                          f"**URL:** [Acessar canal]({youtube_url})",
                color=0x7289DA
            )
            
            # Status atual
            if info and info['is_live']:
                embed.color = 0xFF0000
                embed.add_field(
                    name="🎬 **STATUS ATUAL**",
                    value="✅ **EM LIVE AGORA!**",
                    inline=False
                )
            elif info and info['scheduled_live']:
                embed.color = 0xFFA500
                embed.add_field(
                    name="📅 **STATUS ATUAL**",
                    value="⏰ **Live Programada**",
                    inline=False
                )
            else:
                embed.add_field(
                    name="📊 **STATUS ATUAL**",
                    value="⏸️ **Não está em live**",
                    inline=False
                )
            
            # Configurações
            notify_status = []
            if notify_videos: notify_status.append("✅ Vídeos")
            if notify_lives: notify_status.append("✅ Lives")
            if notify_scheduled: notify_status.append("✅ Programadas")
            
            embed.add_field(
                name="🔔 **Notificações**",
                value="\n".join(notify_status) if notify_status else "❌ Nenhuma",
                inline=True
            )
            
            embed.add_field(
                name="📅 **Configurado**",
                value=f"**Por:** <@{config_user}>\n"
                      f"**Em:** {created[:10]}",
                inline=True
            )
            
            # Últimas atividades
            if last_video:
                embed.add_field(
                    name="📹 **Último Vídeo**",
                    value=f"**{last_video_title[:50]}...**\n"
                          f"⏰ {last_video_time}",
                    inline=False
                )
            
            if last_live:
                embed.add_field(
                    name="🎬 **Última Live**",
                    value=f"**{last_live_title[:50]}...**" if last_live_title else "Detectada",
                    inline=False
                )
            
            # Informações atualizadas
            if info:
                if info['is_live'] and info['live_info']:
                    embed.add_field(
                        name="🎬 **LIVE ATUAL**",
                        value=f"**{info['live_info']['title']}**\n"
                              f"[▶️ Assistir]({info['live_info']['url']})",
                        inline=False
                    )
                    embed.set_image(url=info['live_info']['thumbnail'])
                
                if info['scheduled_live']:
                    embed.add_field(
                        name="📅 **PRÓXIMA LIVE**",
                        value=f"**{info['scheduled_live']['title']}**\n"
                              f"⏰ {info['scheduled_live']['scheduled_time']}",
                        inline=False
                    )
            
            # Comandos de gerenciamento
            embed.add_field(
                name="🔧 **Comandos**",
                value=f"```css\n"
                      f"!yt_settings {youtube_id[:8]} videos on/off\n"
                      f"!yt_settings {youtube_id[:8]} lives on/off\n"
                      f"!yt_settings {youtube_id[:8]} scheduled on/off\n"
                      f"!yt_remove {youtube_id[:8]}\n"
                      f"```",
                inline=False
            )
            
            await processing_msg.edit(content=None, embed=embed)
            
        except Exception as e:
            await processing_msg.edit(content="❌ **Erro ao buscar informações.**")
    
    @commands.command(name='yt_all')
    async def show_all_channels(self, ctx):
        """📋 Mostra todos os canais configurados"""
        configs = db.get_config(ctx.guild.id)
        
        if not configs:
            await ctx.send("❌ **Nenhum canal configurado.** Use `!yt` primeiro.")
            return
        
        await self.show_all_configs(ctx, configs)
    
    @commands.command(name='yt_now')
    async def check_now(self, ctx, identifier=None):
        """⚡ Verifica todos os canais AGORA"""
        configs = db.get_config(ctx.guild.id)
        
        if not configs:
            await ctx.send("❌ **Nenhum canal configurado.** Use `!yt` primeiro.")
            return
        
        if identifier:
            # Verifica um canal específico
            await self.check_single_channel(ctx, identifier)
        else:
            # Verifica TODOS os canais
            await self.check_all_channels(ctx, configs)
    
    async def check_all_channels(self, ctx, configs):
        """Verifica TODOS os canais do servidor"""
        processing_msg = await ctx.send(f"⚡ **Verificando {len(configs)} canal(es)...**")
        
        results = []
        live_count = 0
        scheduled_count = 0
        
        for config in configs:
            config_id, server_id, channel_id, youtube_url, youtube_name, youtube_id, \
            last_video, last_video_title, last_video_time, last_live, last_live_title, \
            scheduled_live, scheduled_live_time, notify_videos, notify_lives, \
            notify_scheduled, config_user, created, last_check, is_active = config
            
            try:
                info = await extract_youtube_info(youtube_url)
                
                if info:
                    status = "⏸️"
                    if info['is_live']:
                        status = "🎬"
                        live_count += 1
                    elif info['scheduled_live']:
                        status = "📅"
                        scheduled_count += 1
                    
                    results.append(f"{status} **{youtube_name}**")
                else:
                    results.append(f"❌ **{youtube_name}** (erro)")
                    
            except:
                results.append(f"❌ **{youtube_name}** (erro)")
        
        embed = discord.Embed(
            title=f"📊 **Verificação Completa - {ctx.guild.name}**",
            description=f"**{len(configs)} canal(es) verificados**\n"
                       f"🎬 **{live_count} em live** • 📅 **{scheduled_count} programadas**",
            color=0x7289DA
        )
        
        # Divide resultados em chunks para não ultrapassar limite do Discord
        chunks = [results[i:i+10] for i in range(0, len(results), 10)]
        
        for i, chunk in enumerate(chunks):
            embed.add_field(
                name=f"**Canais {i*10+1}-{min((i+1)*10, len(results))}**",
                value="\n".join(chunk),
                inline=False
            )
        
        embed.set_footer(text="Use !yt_info [ID] para detalhes de um canal específico")
        await processing_msg.edit(content=None, embed=embed)
    
    async def check_single_channel(self, ctx, identifier):
        """Verifica um canal específico"""
        configs = db.get_config(ctx.guild.id)
        
        target_config = None
        for config in configs:
            config_id, server_id, channel_id, youtube_url, youtube_name, youtube_id, \
            last_video, last_video_title, last_video_time, last_live, last_live_title, \
            scheduled_live, scheduled_live_time, notify_videos, notify_lives, \
            notify_scheduled, config_user, created, last_check, is_active = config
            
            if youtube_id and identifier in youtube_id:
                target_config = config
                break
            elif identifier.lower() in youtube_name.lower():
                target_config = config
                break
        
        if not target_config:
            await ctx.send("❌ **Canal não encontrado.**")
            return
        
        config_id, server_id, channel_id, youtube_url, youtube_name, youtube_id, \
        last_video, last_video_title, last_video_time, last_live, last_live_title, \
        scheduled_live, scheduled_live_time, notify_videos, notify_lives, \
        notify_scheduled, config_user, created, last_check, is_active = target_config
        
        processing_msg = await ctx.send(f"⚡ **Verificando {youtube_name}...**")
        
        try:
            info = await extract_youtube_info(youtube_url)
            
            if not info:
                await processing_msg.edit(content="❌ **Erro ao verificar o canal.**")
                return
            
            embed = discord.Embed(
                title=f"📊 **{youtube_name} - Status Instantâneo**",
                color=0x7289DA,
                timestamp=datetime.now()
            )
            
            # Status atual
            status_text = []
            if info['is_live']:
                status_text.append("🎬 **EM LIVE AGORA!**")
                embed.color = 0xFF0000
            else:
                status_text.append("⏸️ **Não está em live**")
            
            if info['scheduled_live']:
                status_text.append(f"📅 **Live programada:** {info['scheduled_live']['scheduled_time']}")
                embed.color = 0xFFA500 if not info['is_live'] else embed.color
            
            embed.description = "\n".join(status_text)
            
            # Detalhes da live atual
            if info['is_live'] and info['live_info']:
                embed.add_field(
                    name="🎬 **LIVE EM ANDAMENTO**",
                    value=f"**{info['live_info']['title']}**\n"
                          f"[▶️ Assistir]({info['live_info']['url']})",
                    inline=False
                )
                embed.set_image(url=info['live_info']['thumbnail'])
            
            # Live programada
            if info['scheduled_live']:
                embed.add_field(
                    name="📅 **PRÓXIMA LIVE**",
                    value=f"**{info['scheduled_live']['title']}**\n"
                          f"⏰ {info['scheduled_live']['scheduled_time']}\n"
                          f"[🔔 Definir lembrete]({info['scheduled_live']['url']})",
                    inline=False
                )
                if not info['is_live']:
                    embed.set_image(url=info['scheduled_live']['thumbnail'])
            
            # Último vídeo
            if info['latest_video']:
                embed.add_field(
                    name="📹 **ÚLTIMO VÍDEO**",
                    value=f"**{info['latest_video']['title'][:80]}...**\n"
                          f"⏰ {info['latest_video']['publish_time']}\n"
                          f"[▶️ Assistir]({info['latest_video']['url']})",
                    inline=False
                )
                if not info['is_live'] and not info['scheduled_live']:
                    embed.set_thumbnail(url=info['latest_video']['thumbnail'])
            
            embed.set_footer(text=f"ID: {youtube_id[:8]}... • Atualizado agora")
            await processing_msg.edit(content=None, embed=embed)
            
        except Exception as e:
            await processing_msg.edit(content="❌ **Erro na verificação.**")
    
    @commands.command(name='yt_settings')
    @commands.has_permissions(administrator=True)
    async def manage_settings(self, ctx, identifier=None, setting=None, value=None):
        """⚙️ Gerencia configurações de um canal específico"""
        configs = db.get_config(ctx.guild.id)
        
        if not configs:
            await ctx.send("❌ **Nenhum canal configurado.**")
            return
        
        if not identifier:
            # Mostra lista de canais para configurar
            embed = discord.Embed(
                title="⚙️ **Configurar Canal**",
                description="**Selecione um canal:**",
                color=0x7289DA
            )
            
            for config in configs:
                config_id, server_id, channel_id, youtube_url, youtube_name, youtube_id, \
                last_video, last_video_title, last_video_time, last_live, last_live_title, \
                scheduled_live, scheduled_live_time, notify_videos, notify_lives, \
                notify_scheduled, config_user, created, last_check, is_active = config
                
                embed.add_field(
                    name=f"**{youtube_name}**",
                    value=f"`!yt_settings {youtube_id[:8]} [config] [on/off]`",
                    inline=True
                )
            
            embed.add_field(
                name="📋 **Configurações disponíveis:**",
                value="```css\n"
                      "videos     - Notificar novos vídeos\n"
                      "lives      - Notificar lives em andamento\n"
                      "scheduled  - Notificar lives programadas\n"
                      "```",
                inline=False
            )
            
            await ctx.send(embed=embed)
            return
        
        # Procura o canal
        target_config = None
        target_youtube_id = None
        
        for config in configs:
            config_id, server_id, channel_id, youtube_url, youtube_name, youtube_id, \
            last_video, last_video_title, last_video_time, last_live, last_live_title, \
            scheduled_live, scheduled_live_time, notify_videos, notify_lives, \
            notify_scheduled, config_user, created, last_check, is_active = config
            
            if youtube_id and identifier in youtube_id:
                target_config = config
                target_youtube_id = youtube_id
                break
            elif identifier.lower() in youtube_name.lower():
                target_config = config
                target_youtube_id = youtube_id
                break
        
        if not target_config:
            await ctx.send("❌ **Canal não encontrado.**")
            return
        
        config_id, server_id, channel_id, youtube_url, youtube_name, youtube_id, \
        last_video, last_video_title, last_video_time, last_live, last_live_title, \
        scheduled_live, scheduled_live_time, notify_videos, notify_lives, \
        notify_scheduled, config_user, created, last_check, is_active = target_config
        
        if not setting:
            # Mostra configurações atuais do canal específico
            embed = discord.Embed(
                title=f"⚙️ **Configurações - {youtube_name}**",
                description=f"**ID:** `{youtube_id[:8]}...`",
                color=0x7289DA
            )
            
            settings_info = [
                f"{'✅' if notify_videos else '❌'} **Vídeos novos** - `!yt_settings {youtube_id[:8]} videos on/off`",
                f"{'✅' if notify_lives else '❌'} **Lives em andamento** - `!yt_settings {youtube_id[:8]} lives on/off`",
                f"{'✅' if notify_scheduled else '❌'} **Lives programadas** - `!yt_settings {youtube_id[:8]} scheduled on/off`",
            ]
            
            embed.add_field(
                name="🔔 **Notificações**",
                value="\n".join(settings_info),
                inline=False
            )
            
            await ctx.send(embed=embed)
            return
        
        # Processa alteração
        setting_map = {
            'videos': 'notify_videos',
            'video': 'notify_videos',
            'lives': 'notify_lives',
            'live': 'notify_lives',
            'scheduled': 'notify_scheduled',
            'programadas': 'notify_scheduled',
            'programada': 'notify_scheduled'
        }
        
        db_setting = setting_map.get(setting.lower())
        if not db_setting:
            await ctx.send("❌ **Configuração inválida.** Use: `videos`, `lives` ou `scheduled`")
            return
        
        if value and value.lower() in ['on', 'sim', 'yes', 'true', '1', 'ativar', 'ativado']:
            db_value = 1
            status = "✅ **ATIVADO**"
        else:
            db_value = 0
            status = "❌ **DESATIVADO**"
        
        db.update_setting(ctx.guild.id, target_youtube_id, db_setting, db_value)
        
        embed = discord.Embed(
            title="⚙️ **Configuração Alterada**",
            description=f"**{youtube_name}**\n**{setting.capitalize()}:** {status}",
            color=0x00FF00 if db_value else 0xFF0000
        )
        
        await ctx.send(embed=embed)
    
    @commands.command(name='yt_remove')
    @commands.has_permissions(administrator=True)
    async def remove_monitor(self, ctx, identifier=None):
        """🗑️ Remove monitoramento de um canal específico"""
        configs = db.get_config(ctx.guild.id)
        
        if not configs:
            await ctx.send("❌ **Nenhum canal configurado.**")
            return
        
        if not identifier:
            # Mostra lista de canais para remover
            embed = discord.Embed(
                title="🗑️ **Remover Canal**",
                description="**Selecione um canal para remover:**",
                color=0xFF0000
            )
            
            for config in configs:
                config_id, server_id, channel_id, youtube_url, youtube_name, youtube_id, \
                last_video, last_video_title, last_video_time, last_live, last_live_title, \
                scheduled_live, scheduled_live_time, notify_videos, notify_lives, \
                notify_scheduled, config_user, created, last_check, is_active = config
                
                embed.add_field(
                    name=f"**{youtube_name}**",
                    value=f"`!yt_remove {youtube_id[:8]}`",
                    inline=True
                )
            
            embed.set_footer(text="⚠️ Esta ação não pode ser desfeita!")
            await ctx.send(embed=embed)
            return
        
        # Procura o canal
        target_config = None
        target_youtube_id = None
        target_youtube_name = None
        
        for config in configs:
            config_id, server_id, channel_id, youtube_url, youtube_name, youtube_id, \
            last_video, last_video_title, last_video_time, last_live, last_live_title, \
            scheduled_live, scheduled_live_time, notify_videos, notify_lives, \
            notify_scheduled, config_user, created, last_check, is_active = config
            
            if youtube_id and identifier in youtube_id:
                target_config = config
                target_youtube_id = youtube_id
                target_youtube_name = youtube_name
                break
            elif identifier.lower() in youtube_name.lower():
                target_config = config
                target_youtube_id = youtube_id
                target_youtube_name = youtube_name
                break
        
        if not target_config:
            await ctx.send("❌ **Canal não encontrado.**")
            return
        
        # Confirmação
        embed = discord.Embed(
            title="⚠️ **Confirmar Remoção**",
            description=f"**Tem certeza que deseja remover?**\n\n"
                       f"**Canal:** {target_youtube_name}\n"
                       f"**ID:** `{target_youtube_id[:8]}...`\n\n"
                       f"**Esta ação irá:**\n"
                       f"• ❌ Parar o monitoramento\n"
                       f"• 🗑️ Apagar o histórico\n"
                       f"• ⚠️ Não pode ser desfeita!",
            color=0xFF0000
        )
        
        embed.set_footer(text="Digite 'SIM' para confirmar ou 'NÃO' para cancelar")
        await ctx.send(embed=embed)
        
        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel
        
        try:
            msg = await bot.wait_for('message', timeout=30.0, check=check)
            
            if msg.content.upper() == 'SIM':
                if db.delete_config(ctx.guild.id, target_youtube_id):
                    remaining = db.get_server_configs_count(ctx.guild.id)
                    
                    embed = discord.Embed(
                        title="✅ **Canal Removido!**",
                        description=f"**{target_youtube_name}** não será mais monitorado.\n\n"
                                   f"**Canais restantes:** {remaining}\n"
                                   f"**Histórico:** Apagado\n"
                                   f"**Configurações:** Removidas",
                        color=0x00FF00
                    )
                    
                    await ctx.send(embed=embed)
                else:
                    await ctx.send("❌ **Erro ao remover o canal.**")
            else:
                await ctx.send("✅ **Remoção cancelada.**")
                
        except asyncio.TimeoutError:
            await ctx.send("⏰ **Tempo esgotado.** Remoção cancelada.")
    
    @commands.command(name='yt_remove_all')
    @commands.has_permissions(administrator=True)
    async def remove_all_monitors(self, ctx):
        """🗑️ Remove TODOS os canais do servidor"""
        configs = db.get_config(ctx.guild.id)
        
        if not configs:
            await ctx.send("❌ **Nenhum canal configurado.**")
            return
        
        total_canais = len(configs)
        
        # Confirmação
        embed = discord.Embed(
            title="⚠️ **CONFIRMAR REMOÇÃO TOTAL**",
            description=f"**TEM CERTEZA ABSOLUTA?**\n\n"
                       f"**Isso irá remover:**\n"
                       f"• ❌ **{total_canais} canal(es)**\n"
                       f"• 🗑️ **TODO o histórico**\n"
                       f"• ⚠️ **TODAS as configurações**\n\n"
                       f"**Esta ação NÃO PODE SER DESFEITA!**",
            color=0xFF0000
        )
        
        embed.set_footer(text="Digite 'REMOVER TUDO' para confirmar")
        await ctx.send(embed=embed)
        
        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel
        
        try:
            msg = await bot.wait_for('message', timeout=30.0, check=check)
            
            if msg.content.upper() == 'REMOVER TUDO':
                if db.delete_config(ctx.guild.id):
                    embed = discord.Embed(
                        title="✅ **TODOS os Canais Removidos!**",
                        description=f"**{total_canais} canal(es) removidos**\n\n"
                                   f"**Histórico:** Apagado\n"
                                   f"**Configurações:** Removidas\n"
                                   f"**Monitoramento:** Parado",
                        color=0x00FF00
                    )
                    
                    await ctx.send(embed=embed)
                else:
                    await ctx.send("❌ **Erro ao remover os canais.**")
            else:
                await ctx.send("✅ **Remoção cancelada.**")
                
        except asyncio.TimeoutError:
            await ctx.send("⏰ **Tempo esgotado.** Remoção cancelada.")
    
    @commands.command(name='yt_help')
    async def show_help(self, ctx):
        """📚 Mostra ajuda completa"""
        embed = discord.Embed(
            title="📚 **YouTube Monitor MULTI-CANAL**",
            description="**Sistema de monitoramento MULTI-CANAL**\n"
                       "⚡ **Verificação:** A cada 30 segundos!",
            color=0x7289DA
        )
        
        # Comandos principais
        commands_list = [
            ("🎬 `!yt <link>`", "Adicionar novo canal"),
            ("📋 `!yt`", "Ver todos os canais do servidor"),
            ("📋 `!yt_info [ID]`", "Ver detalhes de um canal"),
            ("⚡ `!yt_now`", "Verificar TODOS os canais AGORA"),
            ("⚡ `!yt_now [ID]`", "Verificar um canal específico"),
            ("⚙️ `!yt_settings`", "Gerenciar notificações"),
            ("🗑️ `!yt_remove [ID]`", "Remover um canal"),
            ("🗑️ `!yt_remove_all`", "Remover TODOS os canais"),
            ("📚 `!yt_help`", "Esta mensagem de ajuda")
        ]
        
        for cmd, desc in commands_list:
            embed.add_field(name=cmd, value=desc, inline=False)
        
        # Exemplos
        embed.add_field(
            name="🎯 **Exemplos de Uso:**",
            value="```css\n"
                  "# Adicionar 3 canais diferentes:\n"
                  "!yt https://youtube.com/@canal1\n"
                  "!yt https://youtube.com/@canal2\n"
                  "!yt https://youtube.com/@canal3\n\n"
                  "# Ver todos os canais:\n"
                  "!yt\n\n"
                  "# Verificar todos AGORA:\n"
                  "!yt_now\n\n"
                  "# Configurar um canal específico:\n"
                  "!yt_settings [ID] videos on\n"
                  "```",
            inline=False
        )
        
        # Informações técnicas
        embed.add_field(
            name="⚡ **Tempos de verificação:**",
            value="• **Automático:** 30 segundos\n"
                  "• **Lives:** Detecta em 30-60 segundos\n"
                  "• **Vídeos:** Detecta em 1-2 minutos\n"
                  "• **Programadas:** Detecta imediatamente",
            inline=False
        )
        
        embed.add_field(
            name="✅ **Recursos Multi-Canal:**",
            value="• **Múltiplos canais por servidor**\n"
                  "• **Monitoramento simultâneo**\n"
                  "• **Configurações individuais**\n"
                  "• **Histórico separado**",
            inline=False
        )
        
        embed.set_footer(text="Desenvolvido para múltiplos canais simultâneos!")
        await ctx.send(embed=embed)

# ========== SISTEMA DE MONITORAMENTO MULTI-CANAL ==========
@tasks.loop(seconds=30)
async def multi_channel_monitor():
    """Monitoramento MULTI-CANAL - 30 segundos!"""
    await bot.wait_until_ready()
    
    configs = db.get_active_configs()
    if not configs:
        return
    
    print(f"⚡ Verificando {len(configs)} canais em {len(set(c[1] for c in configs))} servidores...")
    
    for config in configs:
        try:
            config_id, server_id, channel_id, youtube_url, youtube_name, youtube_id, \
            last_video, last_video_title, last_video_time, last_live, last_live_title, \
            scheduled_live, scheduled_live_time, notify_videos, notify_lives, \
            notify_scheduled, config_user, created, last_check, is_active = config
            
            # Pula se não tem notificações ativas
            if not (notify_videos or notify_lives or notify_scheduled):
                continue
            
            guild = bot.get_guild(int(server_id))
            if not guild:
                continue
            
            channel = guild.get_channel(int(channel_id))
            if not channel:
                continue
            
            # Extrai informações
            info = await extract_youtube_info(youtube_url)
            if not info:
                continue
            
            # 1. VERIFICA LIVE EM ANDAMENTO
            if notify_lives and info['is_live'] and info['live_info']:
                live_id = info['live_info']['id']
                
                if live_id and live_id != last_live:
                    # Atualiza banco
                    db.update_live(server_id, youtube_id, live_id, info['live_info']['title'])
                    db.add_history(server_id, youtube_id, live_id, 
                                 info['live_info']['title'], 'live', info['channel_name'])
                    
                    # Envia notificação
                    embed = discord.Embed(
                        title=f"🎬 **{info['channel_name']} ENTROU AO VIVO!**",
                        description=f"**{info['live_info']['title']}**\n\n"
                                  f"🔗 [▶️ Assistir AGORA]({info['live_info']['url']})",
                        color=0xFF0000,
                        url=info['live_info']['url']
                    )
                    embed.set_image(url=info['live_info']['thumbnail'])
                    embed.set_footer(text="⚡ Detectado em menos de 30 segundos!")
                    
                    await channel.send(f"@everyone", embed=embed)
                    print(f"⚡ LIVE: {info['channel_name']} em {guild.name}")
            
            # 2. VERIFICA LIVE PROGRAMADA
            if notify_scheduled and info['scheduled_live']:
                scheduled_id = info['scheduled_live']['id']
                
                if scheduled_id and scheduled_id != scheduled_live:
                    # Atualiza banco
                    db.update_scheduled(server_id, youtube_id, scheduled_id, 
                                       info['scheduled_live']['title'],
                                       info['scheduled_live']['scheduled_time'])
                    db.add_history(server_id, youtube_id, scheduled_id, 
                                 info['scheduled_live']['title'], 'scheduled', info['channel_name'])
                    
                    # Envia notificação
                    embed = discord.Embed(
                        title=f"📅 **{info['channel_name']} PROGRAMOU LIVE!**",
                        description=f"**{info['scheduled_live']['title']}**\n\n"
                                  f"⏰ **Data/Hora:** {info['scheduled_live']['scheduled_time']}\n"
                                  f"🔗 [🔔 Definir lembrete]({info['scheduled_live']['url']})",
                        color=0xFFA500,
                        url=info['scheduled_live']['url']
                    )
                    embed.set_image(url=info['scheduled_live']['thumbnail'])
                    embed.set_footer(text="Live programada detectada")
                    
                    await channel.send(f"📅 **LIVE PROGRAMADA POR {info['channel_name']}!**", embed=embed)
                    print(f"📅 SCHEDULED: {info['channel_name']} em {guild.name}")
            
            # 3. VERIFICA VÍDEO NOVO
            if notify_videos and info['latest_video']:
                video_id = info['latest_video']['id']
                
                if video_id and video_id != last_video:
                    # Atualiza banco
                    db.update_video(server_id, youtube_id, video_id, 
                                   info['latest_video']['title'],
                                   info['latest_video']['publish_time'])
                    db.add_history(server_id, youtube_id, video_id, 
                                 info['latest_video']['title'], 'video', info['channel_name'])
                    
                    # Envia notificação
                    embed = discord.Embed(
                        title=f"📹 **{info['channel_name']} POSTOU VÍDEO NOVO!**",
                        description=f"**{info['latest_video']['title']}**\n\n"
                                  f"⏰ **Publicado:** {info['latest_video']['publish_time']}\n"
                                  f"🔗 [▶️ Assistir agora]({info['latest_video']['url']})",
                        color=0x00FF00,
                        url=info['latest_video']['url']
                    )
                    embed.set_image(url=info['latest_video']['thumbnail'])
                    embed.set_footer(text="Vídeo novo detectado")
                    
                    await channel.send(f"🎬 **NOVO VÍDEO DE {info['channel_name']}!**", embed=embed)
                    print(f"📹 VIDEO: {info['channel_name']} em {guild.name}")
            
            await asyncio.sleep(0.5)  # Pequena pausa entre canais
            
        except Exception as e:
            print(f"❌ Erro monitorando {config[4] if len(config) > 4 else 'desconhecido'}: {e}")
            continue

# ========== EVENTOS ==========
@bot.event
async def on_ready():
    print(f'✅ Bot online: {bot.user.name}')
    print(f'⚡ YouTube Monitor MULTI-CANAL')
    print(f'⏰ Verificação: A cada 30 segundos!')
    print('=' * 50)
    
    # Adiciona cog de comandos
    await bot.add_cog(YouTubeCommands(bot))
    
    # Inicia monitoramento MULTI-CANAL
    multi_channel_monitor.start()
    
    # Verifica quantos canais estão sendo monitorados
    configs = db.get_all_configs()
    servers = set(c[1] for c in configs) if configs else set()
    print(f'📊 Estatísticas:')
    print(f'   • Servidores: {len(servers)}')
    print(f'   • Canais YouTube: {len(configs)}')
    print(f'   • Monitoramento ativo: {len([c for c in configs if c[13] or c[14] or c[15]])}')
    
    # Status do bot
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching,
        name="⚡ !yt_help"
    ))

@bot.event
async def on_guild_join(guild):
    for channel in guild.text_channels:
        if channel.permissions_for(guild.me).send_messages:
            embed = discord.Embed(
                title="⚡ **YouTube Monitor MULTI-CANAL**",
                description="**Monitoramento a cada 30 segundos!**\n\n"
                          "**Recursos MULTI-CANAL:**\n"
                          "• ✅ **Múltiplos canais por servidor**\n"
                          "• ✅ **Monitoramento simultâneo**\n"
                          "• ✅ **Configurações individuais**\n"
                          "• ✅ **Histórico separado**",
                color=0xFF0000
            )
            
            embed.add_field(
                name="🎯 **Como usar:**",
                value="```css\n"
                      "# Adicionar múltiplos canais:\n"
                      "!yt https://youtube.com/@canal1\n"
                      "!yt https://youtube.com/@canal2\n"
                      "!yt https://youtube.com/@canal3\n\n"
                      "# Ver todos os canais:\n"
                      "!yt\n\n"
                      "# Ajuda completa:\n"
                      "!yt_help\n"
                      "```",
                inline=False
            )
            
            await channel.send(embed=embed)
            break

# ========== INICIAR ==========
if __name__ == "__main__":
    print('🚀 Iniciando YouTube Monitor MULTI-CANAL...')
    print('⚡ Verificação: A cada 30 segundos!')
    print('🎯 Sistema MULTI-CANAL: Um servidor pode monitorar VÁRIOS canais!')
    print('📊 Monitoramento simultâneo de múltiplos canais YouTube')
    print('=' * 50)
    
    try:
        bot.run(TOKEN)
    except KeyboardInterrupt:
        print("\n👋 Encerrando...")
    except Exception as e:
        print(f"❌ Erro: {e}")