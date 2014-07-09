var mysql = require('mysql'),
	jsdom = require('jsdom'),
	sql   = mysql.createConnection({
		host     : 'localhost',
		user     : 'node',
		database : 'nfl',
		password : 'asAi7q;tLArhDLqmxTY3#mmuXqBCkRwEZh+Q',
	}),
	clone = function(object) {
	  var newObj = (object instanceof Array) ? [] : {};
	  for (i in object) {
	    if (i == 'clone') continue;
	    if (object[i] && typeof object[i] == "object") {
	      newObj[i] = clone(object[i]);
	    } else newObj[i] = object[i]
	  } return newObj;
	},
	season = 2012,
	publication = 'ESPN';


// sql.connect();


var addGame = function (winner, loser, game) {
	sql.query("SELECT id FROM nfl_teams WHERE name="+sql.escape(loser.name), function(err, rows, fields) {
		loser.id = rows[0].id;
		insertGame();
	});

	sql.query("SELECT id FROM nfl_teams WHERE name="+sql.escape(winner.name), function(err, rows, fields) {
		winner.id = rows[0].id;
		insertGame();
	});

	var insertGame = function () {
		if (!winner.id || !loser.id) return false;

		if (game.location.name == winner.name)
			game.location.id = winner.id;
		else
			game.location.id = loser.id;

		sql.query("SELECT id FROM nfl_games WHERE ((team_1="+sql.escape(winner.id)+" AND team_2="+sql.escape(loser.id)+") OR (team_1="+sql.escape(loser.id)+" AND team_2="+sql.escape(winner.id)+")) AND season="+sql.escape(season)+" AND week="+sql.escape(game.week)+" AND location="+sql.escape(game.location.id), function(err, rows, fields) {
			if (rows.length == 0)
				sql.query("INSERT INTO nfl_games (team_1, team_2, season, week, date, location) VALUES ("+sql.escape(winner.id)+","+sql.escape(loser.id)+","+season+","+sql.escape(game.week)+","+sql.escape(game.date)+","+sql.escape(game.location.id)+");", function(err, rows, fields) {
					if (!err) {
						game.id = rows.insertId;
						sql.query("INSERT INTO nfl_game_stats (id_game, id_team, is_winner, yards, turnovers, points) VALUES ("+sql.escape(game.id)+","+sql.escape(loser.id)+",0,"+sql.escape(loser.yards)+","+sql.escape(loser.turnovers)+","+sql.escape(loser.points)+");", function(err, rows, fields) {
							sql.query("UPDATE nfl_games SET stats_2="+sql.escape(loser.id)+" WHERE id="+sql.escape(game.id));
						});
						sql.query("INSERT INTO nfl_game_stats (id_game, id_team, is_winner, yards, turnovers, points) VALUES ("+sql.escape(game.id)+","+sql.escape(winner.id)+",1,"+sql.escape(winner.yards)+","+sql.escape(winner.turnovers)+","+sql.escape(winner.points)+");", function(err, rows, fields) {
							sql.query("UPDATE nfl_games SET stats_1="+sql.escape(winner.id)+" WHERE id="+sql.escape(game.id));
						});
					}
				});
			else {
				game.id = rows[0].id;
				sql.query("INSERT INTO nfl_game_stats (id_game, id_team, is_winner, yards, turnovers, points) VALUES ("+sql.escape(game.id)+","+sql.escape(loser.id)+",0,"+sql.escape(loser.yards)+","+sql.escape(loser.turnovers)+","+sql.escape(loser.points)+");", function(err, rows, fields) {
					sql.query("UPDATE nfl_games SET stats_2="+sql.escape(loser.id)+" WHERE id="+sql.escape(game.id));
				});
				sql.query("INSERT INTO nfl_game_stats (id_game, id_team, is_winner, yards, turnovers, points) VALUES ("+sql.escape(game.id)+","+sql.escape(winner.id)+",1,"+sql.escape(winner.yards)+","+sql.escape(winner.turnovers)+","+sql.escape(winner.points)+");", function(err, rows, fields) {
					sql.query("UPDATE nfl_games SET stats_1="+sql.escape(winner.id)+" WHERE id="+sql.escape(game.id));
				});
			}
		});
	}
}

// if (false)
jsdom.env(
	"http://web.archive.org/web/20130101103121/http://espn.go.com/nfl/picks/_/week/17",
	['//cdnjs.cloudflare.com/ajax/libs/jquery/2.0.3/jquery.min.js', '//cdnjs.cloudflare.com/ajax/libs/d3/3.2.2/d3.v3.min.js'],
	function (errors, window) {
		var $ = window.$,
			d3 = window.d3,
			$table = $($('table.tablehead')[0]),
			picks = $table.find('tr').filter(function (i,d) {
				return /team/.test($(d).attr('class'));
			})
			names = $($('.colhead')[0]).children().map(function (i,d) {
				return $(d).text();
			}).filter(function (i,d) {
				return d.length >= 2;
			}),
			predictors = {},
			teams = {},
			teamCode = function (code) {
				if (code == 'SF') return 'SFO';
				if (code == 'NO') return 'NOR';
				if (code == 'JAC') return 'JAX';
				if (code == 'SD') return 'SDG';
				if (code == 'WSH') return 'WAS';
				if (code == 'NE') return 'NWE';
				if (code == 'KC') return 'KAN';
				if (code == 'TB') return 'TAM';
				if (code == 'GB') return 'GNB';
				return code;
			},
			teamName = function (backwards) {
				var backwards = backwards.split(' '),
					result = '';
				for (var i = 1; i < backwards.length; i++) {
					result += backwards[i] + ' ';
				};
				return result + backwards[0];
			}
			fullDay = function (code) {
				if (code == 'Wed') return 'wednesday';
				if (code == 'Sun') return 'sunday';
				if (code == 'Thu') return 'thursday';
				if (code == 'Mon') return 'monday';
			};

		var insertPrediction = function (prediction) {
			var _insertPrediction = function () {
				console.log(prediction);
				if (prediction.game.team1ID && prediction.game.team2ID && prediction.winnerID)
					sql.query("SELECT id FROM nfl_games WHERE ((team_1="+sql.escape(prediction.game.team1ID)+" AND team_2="+sql.escape(prediction.game.team2ID)+") OR (team_1="+sql.escape(prediction.game.team2ID)+" AND team_2="+sql.escape(prediction.game.team1ID)+")) AND date="+sql.escape(prediction.game.date), function(err, rows, fields) {
						if (rows.length == 0) console.log('COULD NOT FIND GAME: ' + prediction.game.date);
						else {
							var gameID = rows[0].id;
							sql.query("INSERT INTO nfl_predictions (id_predictor, id_game, id_winner) VALUES ("+sql.escape(prediction.id_predictor)+","+sql.escape(gameID)+","+sql.escape(prediction.winnerID)+");", function(err, rows, fields) {
								console.log('ADDED PREDICTION ' + rows.insertId);
							});
						}
					});
			}
			if (teams[prediction.game.team1]) {
				prediction.game.team1ID = teams[prediction.game.team1];
				_insertPrediction();
			}
			else
				sql.query("SELECT id FROM nfl_teams WHERE code_name="+sql.escape(prediction.game.team1), function(err, rows, fields) {
					if (rows.length == 0) console.log('COULD NOT FIND TEAM: ' + prediction.game.team1);
					prediction.game.team1ID = teams[prediction.game.team1] = rows[0].id;
					_insertPrediction();
				});
			if (teams[prediction.game.team2]) {
				prediction.game.team2ID = teams[prediction.game.team2];
				_insertPrediction();
			}
			else
				sql.query("SELECT id FROM nfl_teams WHERE code_name="+sql.escape(prediction.game.team2), function(err, rows, fields) {
					if (rows.length == 0) console.log('COULD NOT FIND TEAM: ' + prediction.game.team2);
					prediction.game.team2ID = teams[prediction.game.team2]= rows[0].id;
					_insertPrediction();
				});
			if (teams[prediction.winnerName]) {
				prediction.winnerID = teams[prediction.winnerName];
				_insertPrediction();
			}
			else
				sql.query("SELECT id FROM nfl_teams WHERE name="+sql.escape(prediction.winnerName), function(err, rows, fields) {
					if (rows.length == 0)
						console.log('COULD NOT FIND WINNER: ' + prediction.winnerName);
					else
						prediction.winnerID = teams[prediction.winnerName] = rows[0].id;
					_insertPrediction();
				});
		}

		var insertPredictions = function (k) {
			if (k == names.length - 1)
			for (var i = 0; i < picks.length; i++) {
				var cells = $(picks[i]).children(),
					$firstCell = $(cells[0]),
					date = $firstCell.text().slice($firstCell.text().length - ($firstCell.text().split(' ')[$firstCell.text().split(' ').length - 1].length + 4)),
					gameStr = $firstCell.text().slice(0, $firstCell.text().length - ($firstCell.text().split(' ')[$firstCell.text().split(' ').length - 1].length + 4)).split(' '),
					game = {};

				date = d3.time.format('%Y-%m-%d')(d3.time.week.offset(d3.time[fullDay(date.split(' ')[0])](new Date()), 1));
				// date = d3.time.format('%Y-%m-%d')(d3.time[fullDay(date.split(' ')[0])](new Date(2012, 11, 30)));
				game.team1 = teamCode(gameStr[0]);
				game.team2 = teamCode(gameStr[2]);
				game.date = date;

				for (var j = 1; j < cells.length; j++) {
					// console.log($(cells[0]).text());
					// console.log($(cells[4]).text().trim());
					// console.log(names[j-1]);
					// console.log(predictors[names[j-1]]);
					// console.log(teamName($(cells[j]).text().trim()));
					insertPrediction({
						id_predictor: +predictors[names[j-1]],
						game: game,
						winnerName: teamName($(cells[j]).text().trim())
					})
				};

				// console.log(game);
				// console.log(date);
			};
		}

		var addPredictor = function (name,i) {
			sql.query("SELECT id FROM nfl_predictors WHERE name="+sql.escape(name)+" AND publication="+sql.escape(publication), function(err, rows, fields) {
				if (rows.length) {
					predictors[name] = rows[0].id;
					insertPredictions(i);
				}
				else {
					sql.query("INSERT INTO nfl_predictors (name, publication) VALUES ("+sql.escape(name)+","+sql.escape(publication)+");", function(err, rows, fields) {
						predictors[name] = rows.insertId;
						insertPredictions(i);
					});
				}
			});
		}

		for (var i = 0; i < names.length; i++) {
			addPredictor(names[i].slice(0), i);
		};

	}
);
