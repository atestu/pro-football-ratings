#!/Users/juliencapron/.rbenv/shims/ruby

require 'rubygems'
require 'nokogiri'
require 'open-uri'
require 'restclient'

class Parser

  def test_openuri
    page = Nokogiri::HTML(open("http://www.cbssports.com/nfl/features/writers/expert/picks/straight-up/1"))
    puts page.class
    puts page
  end

  def test_restclient
    page = Nokogiri::HTML(RestClient.get("http://www.cbssports.com/nfl/features/writers/expert/picks/straight-up/1"))
    puts page.class
    puts page
  end

  def get_rows
    page = Nokogiri::HTML(RestClient.get("http://www.cbssports.com/nfl/features/writers/expert/picks/straight-up/1"))
    rows = page.css('table#oddsTable tr.row1, table#oddsTable tr.row2')
    rows[0].children[3].attributes["align"].value # => "center"

    rows[0].children.each do |c|
      if c.attributes["align"] && c.attributes["align"].value == "center"
        if c.attributes["width"].value == "60"
          p c.children[0].children[0].attributes["src"].value.split('/').last.split('.').first
          p "******"
        end
      end
    end
  end

  def kanye
    puts "I feel like I'm too busy writing history to read it."
  end

end

# http://www.cbssports.com/nfl/features/writers/expert/picks/straight-up/1
# http://espn.go.com/nfl/schedule/_/year/2013/seasontype/3

# 1 Arizona Cardinals ARI
# 2 Baltimore Ravens BAL
# 3 Carolina Panthers CAR
# 4 Cincinnati Bengals CIN
# 5 Dallas Cowboys DAL
# 6 Detroit Lions DET
# 7 Houston Texans HOU
# 8 Jacksonville Jaguars JAX
# 9 Miami Dolphins MIA
# 10 New England Patriots NWE
# 11 New York Giants NYG
# 12 Oakland Raiders OAK
# 13 Pittsburgh Steelers PIT
# 14 San Francisco 49ers SFO
# 15 St. Louis Rams STL
# 16 Tennessee Titans TEN
# 17 Atlanta Falcons ATL
# 18 Buffalo Bills BUF
# 19 Chicago Bears CHI
# 20 Cleveland Browns CLE
# 21 Denver Broncos DEN
# 22 Green Bay Packers GNB
# 23 Indianapolis Colts IND
# 24 Kansas City Chiefs KAN
# 25 Minnesota Vikings MIN
# 26 New Orleans Saints NOR
# 27 New York Jets NYJ
# 28 Philadelphia Eagles PHI
# 29 San Diego Chargers SDG
# 30 Seattle Seahawks SEA
# 31 Tampa Bay Buccaneers TAM
# 32 Washington Redskins WAS
