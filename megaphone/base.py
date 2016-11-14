import datetime
import json
import math
import time
from collections import namedtuple
from contextlib import suppress

import numpy as np
from dateutil import parser
from megaphone.helpers import parse_payout, read_asset, simple_cache, time_diff
from megaphone.node import Node
from piston.steem import Post as PistonPost
from werkzeug.contrib.cache import SimpleCache


base_cache = SimpleCache()


class AccountError(RuntimeError):
    pass


class Account(object):
    """
    Social blockchain account.
    Currently supported: STEEM and GOLOS.
    """
    def __init__(self, account, chaind=None, blockchain="GOLOS"):
        """
        Initialize Account object.

        :param account: STEEM/GOLOS account name
        :type account: str
        :param chaind: Blockchain node instance (steemd/golosd)
        :type chaind: :py:class:`Node`
        """
        if not chaind:
            chaind = Node().default(blockchain_name=blockchain)
        self.chaind = chaind
        self.account = account
        self.converter = Converter(chaind)

        # caches
        self._blog = None
        self._props = None

    @property
    def reputation(self):
        """
        Account reputation score.

        :return: Reputation score
        :rtype: float
        """
        rep = int(self.get_props()["reputation"])
        if rep < 0:
            return -1
        if rep == 0:
            return 25

        score = (math.log10(abs(rep)) - 9) * 9 + 25
        return float("%.2f" % score)

    @property
    def power(self):
        """
        Account power in STEEM/GOLOS power.

        :return: power value
        :rtype
        """
        vests = int(parse_payout(self.get_props()["vesting_shares"]))
        return self.converter.vests_to_power(vests)

    @property
    def voting_power(self):
        """
        Account voting power.

        :return: voting power value
        :rtype: float
        """
        return self.get_props()['voting_power'] / 100

    @property
    def followers(self):
        return [x['follower'] for x in self._get_followers("follower")]

    @property
    def following(self):
        return [x['following'] for x in self._get_followers("following")]

    def _get_followers(self, direction="follower", last_user=""):
        """
        Return a full list of following/followers.

        :param direction: 'follower' for followers, 'fo
        :type direction: str
        :param last_user: account name to start from
        :type last_user: str

        :return: list of followers
        """
        allowed_directions = ["follower", "following"]
        if direction not in allowed_directions:
            raise AccountError("Allowed directions : %s" % allowed_directions)
        followers = self.chaind.rpc.get_followers(self.account, last_user,
                                                  "blog", 100, api="follow")
        if len(followers) == 100:
            followers += self._get_followers(direction,
                                             followers[-1][direction])[1:]
        return followers

    @property
    def balances(self):
        """
        Return account's GOLOS, GBG ang GESTS balances.

        STEEM blockchain { "steem", "sbd", "vests" }
        GOLOS blockchain { "golos", "gbg", "gests" }

        :return: account's balances
        :rtype: dict
        """
        my_account_balances = self.chain.get_balances(self.account)
        balances = {}
        if self.blockchain_name == "GOLOS":
            balances["golos"] = parse_payout(my_account_balances["balance"])
            balances["gbg"] = parse_payout(my_account_balances["sbd_balance"]),
            balances["gests"] = parse_payout(my_account_balances["vesting_shares"])
        elif self.blockchain_name == "STEEM":
            balances["steem"] = parse_payout(my_account_balances["balance"])
            balances["sbd"] = parse_payout(my_account_balances["sbd_balance"]),
            balances["vests"] = parse_payout(my_account_balances["vesting_shares"])
        return balances

    def get_props(self):
        """
        Get account properties.

        :return: Account properties.
        :rtype: dict
        """
        if self._props is None:
            self._props = self.chain.rpc.get_account(self.account)
        return self._props

    def get_blog(self):
        """
        Get account blog in JSON format.

        :return:
        """
        if self._blog is None:
            def _get_blog(chain, user):
                state = chain.rpc.get_state("/@%s/blog" % user)
                posts = state["accounts"][user].get("blog", [])
                return [PistonPost(chain, "@%s" % x) for x in posts if x]
            self._blog = _get_blog(self.chain, self.account)
        return self._blog

    def number_of_winning_posts(self, skip=1, payout_requirement=300,
                                max_posts=10):
        """
        Get number of winning posts.

        :param skip:
        :param payout_requirement:
        :param max_posts:
        :return:
        """
        winning_posts = 0
        blog = self.get_blog()[skip:max_posts + skip]
        for post in blog:
            total_payout = parse_payout(post['total_payout_reward'])
            if total_payout >= payout_requirement:
                winning_posts += 1

        nt = namedtuple('WinningPosts', ['winners', 'blog_posts'])
        return nt(winning_posts, len(blog))

    def avg_payout_per_post(self, skip=1, max_posts=10):
        """
        Return average payout per post.

        :param skip:
        :param max_posts:

        :return:
        """
        total_payout = 0
        blog = self.get_blog()[skip:max_posts + skip]
        for post in blog:
            total_payout += parse_payout(post['total_payout_reward'])

        if len(blog) == 0:
            return 0

        return total_payout / len(blog)

    def time_to_whale(self, verbose=False, whale_sp=1e5, skip=1, max_posts=10,
                      mean_of_recent=3):
        blog = self.get_blog()[skip:max_posts + skip]

        max_rshares = self.converter.sp_to_rshares(whale_sp)
        time_to_whale = []

        for post in blog:
            votes = []
            rshares_sum = 0

            for vote in post['active_votes']:
                vote['time_elapsed'] = int(time_diff(post['created'], vote['time']))
                votes.append(vote)

            # note: this function will already filter out posts without votes
            for vote in sorted(votes, key=lambda k: k['time_elapsed']):
                rshares_sum += int(vote['rshares'])
                if rshares_sum >= max_rshares:
                    ttw = time_diff(post['created'], vote['time'])
                    if verbose:
                        print('%s on %s' % (ttw, post['permlink']))
                    time_to_whale.append(ttw)
                    break

        if len(time_to_whale) == 0:
            return None
        return np.mean(time_to_whale[:mean_of_recent])

    def check_if_already_voted(self, post):
        """
        Check if already voted.

        :param post:
        :return:
        """
        for v in self.history2(filter_by="vote"):
            vote = v['op']
            if vote['permlink'] == post['permlink']:
                return True

        return False

    def curation_stats(self):
        """
        Curation statistics.

        :return:
        """
        trailing_24hr_t = time.time() - datetime.timedelta(hours=24).total_seconds()
        trailing_7d_t = time.time() - datetime.timedelta(days=7).total_seconds()

        reward_24h = 0.0
        reward_7d = 0.0

        for event in self.history2(filter_by="curation_reward", take=10000):

            if parser.parse(event['timestamp'] + "UTC").timestamp() > trailing_7d_t:
                reward_7d += parse_payout(event['op']['reward'])

            if parser.parse(event['timestamp'] + "UTC").timestamp() > trailing_24hr_t:
                reward_24h += parse_payout(event['op']['reward'])

        reward_7d = self.converter.vests_to_power(reward_7d)
        reward_24h = self.converter.vests_to_power(reward_24h)
        return {
            "24hr": reward_24h,
            "7d": reward_7d,
            "avg": reward_7d / 7,
        }

    def get_features(self, max_posts=10, payout_requirement=300):
        num_winning_posts, post_count = self.number_of_winning_posts(payout_requirement=payout_requirement,
                                                                     max_posts=max_posts)
        return {
            "name": self.account,
            "settings": {
                "max_posts": max_posts,
                "payout_requirement": payout_requirement,
            },
            "author": {
                "post_count": post_count,
                "winners": num_winning_posts,
                "sp": int(self.get_power()),
                "rep": self.reputation(),
                "followers": len(self.get_followers()),
                "ttw": self.time_to_whale(max_posts=max_posts),
                "ppp": self.avg_payout_per_post(max_posts=max_posts),
            },
        }

    def virtual_op_count(self):
        try:
            last_item = self.golos.rpc.get_account_history(self.account, -1, 0)[0][0]
        except IndexError:
            return 0
        else:
            return last_item

    def history(self, filter_by=None, start=0):
        """
        Take all elements from start to last from history, oldest first.
        """
        batch_size = 1000
        max_index = self.virtual_op_count()
        if not max_index:
            return

        start_index = start + batch_size
        i = start_index
        while True:
            if i == start_index:
                limit = batch_size
            else:
                limit = batch_size - 1
            history = self.golos.rpc.get_account_history(self.account, i, limit)
            for item in history:
                index = item[0]
                if index >= max_index:
                    return

                op_type = item[1]['op'][0]
                op = item[1]['op'][1]
                timestamp = item[1]['timestamp']
                trx_id = item[1]['trx_id']

                def construct_op():
                    return {
                        "index": index,
                        "trx_id": trx_id,
                        "timestamp": timestamp,
                        "op_type": op_type,
                        "op": op,
                    }

                if filter_by is None:
                    yield construct_op()
                else:
                    if type(filter_by) is list:
                        if op_type in filter_by:
                            yield construct_op()

                    if type(filter_by) is str:
                        if op_type == filter_by:
                            yield construct_op()
            i += batch_size

    def history2(self, filter_by=None, take=1000):
        """
        Take X elements from most recent history, oldest first.
        """
        max_index = self.virtual_op_count()
        start_index = max_index - take
        if start_index < 0:
            start_index = 0

        return self.history(filter_by, start=start_index)

    def get_account_votes(self):
        return self.golos.rpc.get_account_votes(self.account)

    def get_withdraw_routes(self):
        return self.golos.rpc.get_withdraw_routes(self.account, 'all')

    def get_conversion_requests(self):
        return self.golos.rpc.get_conversion_requests(self.account)

    @staticmethod
    def filter_by_date(items, start_time, end_time=None):
        start_time = parser.parse(start_time + "UTC").timestamp()
        if end_time:
            end_time = parser.parse(end_time + "UTC").timestamp()
        else:
            end_time = time.time()

        filtered_items = []
        for item in items:
            if 'time' in item:
                item_time = item['time']
            elif 'timestamp' in item:
                item_time = item['timestamp']
            timestamp = parser.parse(item_time + "UTC").timestamp()
            if end_time > timestamp > start_time:
                filtered_items.append(item)

        return filtered_items


class Post(PistonPost):
    """
    Enhanced Piston Post.
    """
    def __init__(self, post, chain=None):
        if not chain:
            chain = Node().default()
        if isinstance(post, PistonPost):
            post = post.identifier
        super(Post, self).__init__(chain, post)

    @property
    def meta(self):
        """
        JSON metadata of the post.

        :return: post metadata
        :rtype: json
        """
        meta = {}
        with suppress(Exception):
            meta_str = self.get("json_metadata", "")
            meta = json.loads(meta_str)
        return meta

    def is_comment(self):
        """
        Return True if post is a comment. Post is a comment if it has an empty
        title, its depth is greater than zero or it does have a parent author.

        :return: True if post is a comment, false otherwise
        :rtype: bool
        """
        if len(self["title"]) == 0 or self["depth"] > 0 \
                or len(self["parent_author"]) > 0:
            return True
        else:
            return False

    def get_votes(self, from_account=None):
        """

        :param from_account:
        :return:
        """
        votes = []
        for vote in self['active_votes']:
            vote['time_elapsed'] = int(time_diff(self['created'], vote['time']))
            if from_account and vote['voter'] == from_account:
                return vote
            votes.append(vote)
        return votes

    def get_metadata(self):
        rshares = int(self["vote_rshares"])
        weight = int(self["total_vote_weight"])

        if int(self["total_vote_weight"]) == 0 and self.time_elapsed() > 3600:
            weight = 0
            rshares = 0
            for vote in self['active_votes']:
                weight += int(vote['weight'])
                rshares += int(vote['rshares'])

        return {
            "rshares": rshares,
            "weight": weight,
            "time_elapsed": self.time_elapsed(),
        }

    def contains_tags(self, filter_by=('spam', 'test', 'nsfw')):
        for tag in filter_by:
            if tag in self['_tags']:
                return True

        return False

    def get_url(self):
        return "https://steemit.com/%s/%s" % (self.category, self.identifier)

    def time_elapsed(self):
        created_at = parser.parse(self['created'] + "UTC").timestamp()
        now_adjusted = time.time()
        return now_adjusted - created_at

    def payout(self):
        return parse_payout(self['total_payout_reward'])

    def calc_reward_pct(self):
        reward = (self.time_elapsed() / 1800) * 100
        if reward > 100:
            reward = 100
        return reward


class Converter(object):
    def __init__(self, chain=None):
        if not chain:
            chain = Node().default()
        self.steem = chain
        self.CONTENT_CONSTANT = 2000000000000

    @simple_cache(base_cache, timeout=5 * 60)
    def sbd_median_price(self):
        return read_asset(self.steem.rpc.get_feed_history()['current_median_history']['base'])['value']

    @simple_cache(base_cache, timeout=5 * 60)
    def steem_per_mvests(self):
        info = self.steem.rpc.get_dynamic_global_properties()
        return (
            parse_payout(info["total_vesting_fund_steem"]) /
            (parse_payout(info["total_vesting_shares"]) / 1e6)
        )

    def vests_to_power(self, vests):
        return vests * self.steem_per_mvests() / 1e6

    def sp_to_vests(self, sp):
        return sp * 1e6 / self.steem_per_mvests()

    def sp_to_rshares(self, sp, voting_power=10000, vote_pct=10000):
        # calculate our account voting shares (from vests), mine is 6.08b
        vesting_shares = int(self.sp_to_vests(sp) * 1e6)

        # calculate vote rshares
        power = (((voting_power * vote_pct) / 10000) / 200) + 1
        rshares = (power * vesting_shares) / 10000

        return rshares

    def steem_to_sbd(self, amount_steem):
        return self.sbd_median_price() * amount_steem

    def sbd_to_steem(self, amount_sbd):
        return amount_sbd / self.sbd_median_price()

    def sbd_to_shares(self, sbd_payout):
        steem_payout = self.sbd_to_steem(sbd_payout)

        props = self.steem.rpc.get_dynamic_global_properties()
        total_reward_fund_steem = read_asset(props['total_reward_fund_steem'])['value']
        total_reward_shares2 = int(props['total_reward_shares2'])

        post_rshares2 = (steem_payout / total_reward_fund_steem) * total_reward_shares2

        rshares = math.sqrt(self.CONTENT_CONSTANT ** 2 + post_rshares2) - self.CONTENT_CONSTANT
        return rshares

    def rshares_2_weight(self, rshares):
        _max = 2 ** 64 - 1
        return (_max * rshares) / (2 * self.CONTENT_CONSTANT + rshares)

