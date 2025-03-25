import random
import time
import sqlite3
from datetime import datetime, timezone
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from typing import Optional
from astrbot.api.all import *

class LotteryServer:
    def __init__(self, db_path='./data/scratch.db'):
        self.db_path = db_path
        self.max_daily_attempts = 3  # 每日最多参与3次
        
        # 初始化数据库字段
        self._init_db()

    def _init_db(self):
        """初始化数据库并添加大乐透相关字段"""
        with sqlite3.connect(self.db_path) as conn:
            # 添加每日次数字段
            try:
                conn.execute('ALTER TABLE users ADD COLUMN daily_lottery_count INTEGER DEFAULT 0;')
            except sqlite3.OperationalError:
                pass
            # 添加最后参与日期字段
            try:
                conn.execute('ALTER TABLE users ADD COLUMN last_lottery_date DATE;')
            except sqlite3.OperationalError:
                pass

    def play_lottery(self, user_id: str) -> dict:
        """大乐透核心逻辑"""
        with sqlite3.connect(self.db_path) as conn:
            conn.isolation_level = 'IMMEDIATE'  # 使用立即锁定模式
            cur = conn.cursor()
            
            try:
                # 获取并锁定用户数据
                user = cur.execute(
                    'SELECT balance, last_lottery_date, daily_lottery_count FROM users WHERE user_id = ?',
                    (user_id,)
                ).fetchone()
                
                if not user:
                    return {'success': False, 'msg': '用户不存在'}
                
                balance = user[0]
                last_date = user[1]
                used_count = user[2] or 0
                today = datetime.now(tz=timezone.utc).date()
                
                # 检查当日次数
                if last_date and datetime.strptime(last_date, '%Y-%m-%d').date() == today:
                    if used_count >= self.max_daily_attempts:
                        return {'success': False, 'msg': '今日次数已用完'}
                    new_count = used_count + 1
                else:
                    new_count = 1

                # 检查余额有效性
                if balance <= 0:
                    return {'success': False, 'msg': '余额不足'}

                # 扣除全部余额作为赌注
                bet_amount = balance
                cur.execute('UPDATE users SET balance = 0 WHERE user_id = ?', (user_id,))
                
                # 生成随机结果
                rand = random.randint(1, 100)
                if rand <= 33:  # 输光
                    result_amount = 0
                    msg = "💸 输的一塌糊涂！所有喵喵币都打水漂了"
                elif rand <= 66:  # 退回
                    result_amount = bet_amount
                    msg = "🛡️ 安如磐石！喵喵币如数奉还"
                elif rand <= 99:  # 双倍
                    result_amount = bet_amount * 2
                    msg = "🍀 有点幸运！获得双倍喵喵币"
                else:  # 十倍（1%概率）
                    result_amount = bet_amount * 10
                    msg = "🌈 天降之子！获得十倍喵喵币！！"

                # 更新最终余额
                cur.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?',
                          (result_amount, user_id))
                
                # 更新参与记录
                cur.execute('''UPDATE users SET
                            last_lottery_date = ?,
                            daily_lottery_count = ?
                            WHERE user_id = ?''',
                            (today.isoformat(), new_count, user_id))
                
                conn.commit()
                return {
                    'success': True,
                    'msg': msg,
                    'bet': bet_amount,
                    'result': result_amount,
                    'balance': result_amount,
                    'remaining_attempts': self.max_daily_attempts - new_count
                }

            except sqlite3.OperationalError as e:
                logger.error(f"数据库锁定错误: {str(e)}")
                return {'success': False, 'msg': '系统繁忙，请稍后再试'}
            except Exception as e:
                conn.rollback()
                logger.error(f"大乐透异常: {str(e)}")
                return {'success': False, 'msg': '系统错误'}

@register("lotto", "Yuki Soffd", "大乐透插件，搏一搏单车变摩托", "1.0.0", "https://github.com/Soffd/astrbot_plugin_lotto")
class LotteryPlugin(Star):
    server = LotteryServer()
    
    def __init__(self, context: Context):
        super().__init__(context)
        
    @filter.command("进行大乐透")
    async def lottery_command(self, event: AstrMessageEvent):
        '''参与大乐透（每日限3次）'''
        user_id = event.get_sender_id()
        result = self.server.play_lottery(user_id)
        
        if result['success']:
            response = [
                f"🎰 {result['msg']}",
                f"▸ 投入金额: {result['bet']}喵喵币",
                f"▸ 获得金额: {result['result']}喵喵币",
                f"💰 当前余额: {result['balance']}",
                f"📅 剩余次数: {result['remaining_attempts']}次"
            ]
        else:
            response = [f"❌ {result['msg']}"]
        
        yield event.plain_result("\n".join(response))

    @filter.command("大乐透帮助")
    async def lottery_help_command(self, event: AstrMessageEvent):
        '''显示大乐透规则'''
        help_text = """
        🎰 大乐透帮助

        1. 参与规则:
        - 每个用户每天最多可以参与 3 次。
        - 每次参与时需要消耗当前账户全部余额（即投注金额），并根据随机结果获得不同的回报。
        
        2. 奖励规则:
        - 33% 的概率获得 0 喵喵币（全亏）。
        - 33% 的概率获得 1 倍投注金额（本金返还）。
        - 33% 的概率获得 2 倍投注金额（双倍回报）。
        - 1% 的概率获得 10 倍投注金额（大奖）。

        3. 余额不足:
        - 如果账户余额为 0，不能参与大乐透。

        使用 /进行大乐透 来参与游戏，祝你好运！🍀
        """
        yield event.plain_result(help_text)