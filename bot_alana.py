from argparse import ArgumentParser
from datetime import datetime
import logging

from flask import Flask, request
from flask_restful import Api

from regexes_intent_classifier import regex_intent_classifier
from utils.utils import log
from utils.utils.abstract_classes import Bot
from utils.utils.dict_query import DictQuery

from answer_with_bert import get_bert_model
from dm_engagement_strategy import dialogue_manager_s1
from dm_baseline import dialogue_manager
from fsm import ConversationFMS
from nlu import get_intent, get_model
from state import State
from story import get_story_graph

import os

app = Flask(__name__)

api = Api(app)
BOT_NAME = "storyteller"
VERSION = log.get_short_git_version()
BRANCH = log.get_git_branch()

logger = logging.getLogger(__name__)

parser = ArgumentParser()
parser.add_argument('-p', "--port", type=int, default=5130)
parser.add_argument('-l', '--logfile', type=str, default='logs/' + BOT_NAME + '.log')
parser.add_argument('-cv', '--console-verbosity', default='info', help='Console logging verbosity')
parser.add_argument('-fv', '--file-verbosity', default='info', help='File logging verbosity')

state_object = None
story_fsm = None
interpreter = get_model()
bert_model = get_bert_model()


class StorytellerBot(Bot):
    def __init__(self, **kwargs):
        super(StorytellerBot, self).__init__(bot_name=BOT_NAME)

    def get(self):
        pass

    def post(self):

        request_data = request.get_json(force=True)

        # We wrap the resulting dictionary in a custom object that allows data access via dot-notation
        request_data = DictQuery(request_data)

        # -------------------- TAKE NEEDED INFO FROM ALANA  ------------------------------ #
        user_utterance = request_data.get("current_state.state.nlu.annotations.processed_text")
        print(user_utterance)
        # -------------------- INITIALISE STATE OBJECT IF NONE------------------------------ #
        global state_object
        if state_object is None:
            # need to create the story graph
            story_graph = get_story_graph()
            visited_nodes = []
            intent = ""
            previous_intent = ""
            state_object = State(story_graph, visited_nodes, user_utterance, intent, bert_model, previous_intent)
        else:
            state_object.utterance = user_utterance
            state_object.previous_intent = state_object.intent
            state_object.intent = ""
        # --------------------- NATURAL LANGUAGE UNDERSTANDING  --------------------- #
        # We try to use regex and if else statement to catch the intent before using rasa
        regex_intent_classifier(user_utterance, state_object)
        if state_object.intent == "":
            nlu_result = get_intent(interpreter, user_utterance)
            state_object.intent = nlu_result["intent"]["name"]
        # initialise fsm
        global story_fsm
        if story_fsm is None:
            story_fsm = ConversationFMS("introduction")
        # set new state
        state_object.set_new_state(story_fsm)

        # -------------------- DIALOGUE MANAGER ------------------ #
        answer = dialogue_manager(state_object, story_fsm)

        logger.info("------- Turn info ----------")
        logger.info("User utterance: {}".format(user_utterance))
        logger.info("User intent: {}".format(state_object.intent))
        logger.info("Bot state: {}".format(story_fsm.state))
        logger.info("Bot answer: {}".format(answer))
        logger.info("---------------------------")

        # ---------------------------------------------------------- #
        self.response.result = answer
        self.response.bot_params["time"] = str(datetime.now())
        self.response.bot_params["lock_requested"] = True
        print(self.response.toJSON())
        # The response generated by the bot is always considered as a list (we allow a bot to generate multiple response
        # objects for the same turn). Here we create a singleton list with the response in JSON format
        return [self.response.toJSON()]


# ----------------- probably need to change this part to connect it with telegram ----------------------

if __name__ == "__main__":

    args = parser.parse_args()

    if not os.path.exists("logs/"):
        os.makedirs("logs/")

    log.set_logger_params(BOT_NAME + '-' + BRANCH, logfile=args.logfile,
                          file_level=args.file_verbosity, console_level=args.console_verbosity)

    api.add_resource(StorytellerBot, "/")

    app.run(host="0.0.0.0", port=args.port)