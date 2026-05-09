import discord
from discord.ext import commands
import asyncio
import random
import os

# === НАСТРОЙКИ (ОБЯЗАТЕЛЬНО ЗАМЕНИТЬ НА СВОИ) ===
# ID голосового канала "Зона ожидания" (куда заходят игроки перед игрой)
LOBBY_CHANNEL_ID = YOUR_LOBBY_VOICE_CHANNEL_ID
# ID категории, где будут создаваться временные комнаты
CATEGORY_ID = YOUR_CATEGORY_ID
# Количество человек в одной временной комнате (2 = пары, 3 = тройки)
GROUP_SIZE = 2
# Время в секундах между циклами перемешивания (300 = 5 минут)
ROTATION_INTERVAL = 300
# Время в секундах, сколько участники находятся во временных комнатах (600 = 10 минут)
# Эту переменную не нужно менять в коде, она указана в функции bring_back_delay
# =============================================

# Включаем все необходимые намерения (Intents)
intents = discord.Intents.default()
intents.members = True        # Чтобы видеть участников
intents.message_content = True
intents.voice_states = True   # Чтобы работать с голосовыми каналами

bot = commands.Bot(command_prefix='!', intents=intents)

# Словарь для хранения созданных временных каналов
temp_channels = {}

@bot.event
async def on_ready():
    """Событие, когда бот успешно запустился"""
    print(f'✅ Бот "{bot.user.name}" успешно запущен!')
    print(f'🎯 ID канала ожидания: {LOBBY_CHANNEL_ID}')
    print(f'🎯 ID категории: {CATEGORY_ID}')
    
    # Проверяем, что бот видит указанные каналы
    lobby = bot.get_channel(LOBBY_CHANNEL_ID)
    category = bot.get_channel(CATEGORY_ID)
    
    if lobby is None:
        print(f'❌ ОШИБКА: Не найден канал ожидания с ID {LOBBY_CHANNEL_ID}')
        print('Проверьте правильность ID и права бота на сервере!')
    else:
        print(f'✅ Канал ожидания "{lobby.name}" найден')
        
    if category is None:
        print(f'❌ ОШИБКА: Не найдена категория с ID {CATEGORY_ID}')
        print('Проверьте правильность ID и права бота на сервере!')
    else:
        print(f'✅ Категория "{category.name}" найдена')
    
    # Запускаем бесконечный цикл перемешивания
    bot.loop.create_task(shuffle_loop())

async def shuffle_loop():
    """Бесконечный цикл, который запускает перемешивание каждые ROTATION_INTERVAL секунд"""
    await bot.wait_until_ready()
    while not bot.is_closed():
        await shuffle_participants()
        await asyncio.sleep(ROTATION_INTERVAL)

async def shuffle_participants():
    """Основная функция: перемешивает участников по временным комнатам"""
    # Защищаем функцию от критических ошибок, чтобы цикл не прерывался
    try:
        # 1. Получаем канал ожидания
        lobby = bot.get_channel(LOBBY_CHANNEL_ID)
        if lobby is None:
            print("❌ Не удалось найти канал ожидания. Перемешивание отменено.")
            return

        # 2. Получаем список реальных участников в канале (исключаем ботов)
        members = [m for m in lobby.members if not m.bot]
        
        # 3. Проверяем, достаточно ли участников для игры
        if len(members) < GROUP_SIZE:
            print(f"👤 Недостаточно участников для перемешивания: {len(members)}/{GROUP_SIZE}. Ждем следующего цикла.")
            return

        print(f"🃏 Начинаем перемешивание! Участников в лобби: {len(members)}")

        # 4. Перемешиваем и разбиваем на группы
        random.shuffle(members)
        groups = [members[i:i + GROUP_SIZE] for i in range(0, len(members), GROUP_SIZE)]

        # 5. Удаляем все старые временные каналы
        for channel_id in list(temp_channels.keys()):
            channel = bot.get_channel(channel_id)
            if channel:
                await channel.delete()
            del temp_channels[channel_id]

        # 6. Получаем категорию для создания новых каналов
        category = bot.get_channel(CATEGORY_ID)
        if category is None:
            print("❌ Не удалось найти категорию для создания комнат. Операция отменена.")
            return

        # 7. Создаем новые комнаты и распределяем участников
        for i, group in enumerate(groups):
            if len(group) < 2:
                # Если в группе остался один человек — отправляем его обратно в лобби
                for member in group:
                    await member.move_to(lobby)
                continue

            # Создаем новый голосовой канал внутри категории
            new_channel = await category.create_voice_channel(
                name=f"🤫│комната-{i + 1}",
                reason="Автоматическое создание для слепого чата"
            )

            # Настраиваем права: канал видят и могут войти только участники группы
            await new_channel.set_permissions(lobby.guild.default_role, view_channel=False, connect=False)
            for member in group:
                await new_channel.set_permissions(member, view_channel=True, connect=True, speak=True)

            # Перемещаем участников в новую комнату
            for member in group:
                await member.move_to(new_channel)

            # Сохраняем канал в словарь для последующего удаления
            temp_channels[new_channel.id] = new_channel
            print(f"✅ Создана комната {i + 1}: {', '.join([m.display_name for m in group])}")

        # 8. Задача: через 10 минут собрать всех обратно в лобби
        # Создаем отдельную задачу, чтобы не блокировать основной цикл
        bot.loop.create_task(bring_everyone_back(lobby, temp_channels.copy()))

    except discord.Forbidden:
        print("❌ Ошибка прав доступа! Убедитесь, что у бота есть права: 'Управлять каналами' и 'Перемещать участников'.")
    except Exception as e:
        print(f"❌ Непредвиденная ошибка при перемешивании: {e}")

async def bring_everyone_back(lobby, channels_to_clean):
    """Вспомогательная функция: собирает всех обратно в лобби и удаляет временные каналы"""
    # Ждем 10 минут (600 секунд) перед сбором
    await asyncio.sleep(600)
    
    print("🔄 Собираем всех участников обратно в лобби...")
    for channel_id, channel in channels_to_clean.items():
        # Получаем актуальный канал (на случай, если он был удален раньше)
        current_channel = bot.get_channel(channel_id)
        if current_channel:
            # Перемещаем каждого участника из канала в лобби
            for member in current_channel.members:
                try:
                    await member.move_to(lobby)
                except discord.Forbidden:
                    print(f"❌ Нет прав для перемещения участника {member.display_name}")
                except Exception as e:
                    print(f"⚠️ Не удалось переместить {member.display_name}: {e}")
            
            # Удаляем временный канал
            try:
                await current_channel.delete()
            except discord.Forbidden:
                print(f"❌ Нет прав для удаления канала {channel.name}")
            except Exception as e:
                print(f"⚠️ Не удалось удалить канал {channel.name}: {e}")
    
    # Очищаем словарь с временными каналами
    temp_channels.clear()
    print("✅ Все участники возвращены в лобби, временные комнаты удалены.")

# --- АДМИНИСТРАТИВНЫЕ КОМАНДЫ ДЛЯ УПРАВЛЕНИЯ БОТОМ (ОПЦИОНАЛЬНО) ---
@bot.command(name='shuffle')
@commands.has_permissions(administrator=True)
async def manual_shuffle(ctx):
    """Ручная команда для принудительного перемешивания. !shuffle"""
    await ctx.send("🔄 Администратор запустил принудительное перемешивание!")
    await shuffle_participants()

@bot.command(name='stop_chat')
@commands.has_permissions(administrator=True)
async def stop_chat(ctx):
    """Команда для остановки текущего раунда и возврата всех в лобби."""
    await ctx.send("⏸️ Администратор остановил текущую сессию. Все возвращаются в лобби!")
    lobby = bot.get_channel(LOBBY_CHANNEL_ID)
    if lobby:
        # Возвращаем всех участников из временных каналов в лобби
        for channel_id, channel in list(temp_channels.items()):
            current_channel = bot.get_channel(channel_id)
            if current_channel:
                for member in current_channel.members:
                    await member.move_to(lobby)
                await current_channel.delete()
        temp_channels.clear()

@bot.command(name='status')
@commands.has_permissions(administrator=True)
async def status(ctx):
    """Показывает текущий статус бота."""
    lobby = bot.get_channel(LOBBY_CHANNEL_ID)
    active_rooms = len(temp_channels)
    players_in_lobby = len([m for m in lobby.members if not m.bot]) if lobby else 0
    await ctx.send(f"**Статус:**\n🟢 Бот активен.\n👥 В лобби: {players_in_lobby} игроков.\n🎲 Активных игровых комнат: {active_rooms}.")

# --- ЗАПУСК БОТА ---
if __name__ == "__main__":
    TOKEN = os.environ.get('TOKEN')
    if not TOKEN:
        print("❌ КРИТИЧЕСКАЯ ОШИБКА: Токен бота не найден!")
        print("Установи переменную окружения TOKEN или укажи токен в коде для теста.")
        # ТОЛЬКО ДЛЯ ЛОКАЛЬНОГО ТЕСТА (никогда не загружай с этим токеном на хостинг!)
        # TOKEN = "ВСТАВЬ_СВОЙ_ТОКЕН_ДЛЯ_ТЕСТА"
    else:
        try:
            bot.run(TOKEN)
        except discord.LoginFailure:
            print("❌ ОШИБКА: Неверный токен. Проверь правильность токена бота в настройках.")
        except Exception as e:
            print(f"❌ Непредвиденная ошибка при запуске: {e}")
