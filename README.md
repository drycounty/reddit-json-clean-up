# reddit-json-clean-up
Reddit JSON cleanup tool that removes most of the non-context stuff to save you tokens when you import a thread's JSON into a LLM

Notes:

* presents itself as a browser
* uses old.reddit.com if that fails


to use:

1. download reddit_clean.py to a directory
2. open a reddit thread ( ie. https://www.reddit.com/r/daddit/comments/1x9j7a3/my_son_has_gotten_into_paw_patrol_and_its_so_bad/ )
3. remove the final slash and everything that populates after that and add.json ie:
```
  https://www.reddit.com/r/daddit/comments/1x9j7a3/my_son_has_gotten_into_paw_patrol_and_its_so_bad.json
```
4. save this as **thread.json** to the same directory as reddit_clean.py
5. run reddit_clean.py and it will output **thread.md**
