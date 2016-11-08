from pprint import pprint

from megaphone.blockchain import Blockchain

# parse the entire blockchain
for event in Blockchain().replay():
    print("Event: %s" % event['op_type'])
    print("Time: %s" % event['timestamp'])
    print("Body: %s\n" % event['op'])

# give me just payments from specific day until now
b = Blockchain()
history = b.replay(
    start_block=b.get_block_from_time("2016-09-01T00:00:00"),
    end_block=b.get_current_block(),
    filter_by=['transfer']
)
for event in history:
    payment = event['op']
    print("@%s sent %s to @%s" % (payment['from'], payment['amount'], payment['to']))

# Output:
# @victoriart sent 1.000 GBG to @null
# @dude sent 5.095 GOLOS to @bittrex
# @devil sent 5.107 GOLOS to @poloniex
# @pinoytravel sent 0.010 GBG to @null
# @aladdin sent 5.013 GOLOS to @poloniex
# @mrwang sent 31.211 GOLOS to @blocktrades
# @kodi sent 0.030 GBG to @steembingo
