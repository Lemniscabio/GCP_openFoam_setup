import random
import re

# Static, curated codenames: themed seeds followed by pronounceable animals,
# colors, adjectives, foods, objects, plants, weather, and other concrete nouns.
_WORD_TEXT = """
falcon raven lynx otter gecko panda robin wolf finch tiger puma heron
ferret moose bison crane newt hawk swan ember frost storm blaze flint
spark dusk comet nova flare gale haze drift thaw mist glow surge
bolt rain snow jade onyx opal ruby amber cobalt slate coral pearl
azure ivory crimson teal olive umber ochre mauve rust mango cocoa maple
basil plum kiwi pepper melon mocha guava peach cherry lemon honey ginger
nutmeg clove sage thyme berry turbo ninja rocket disco mojo banjo tango
bongo pixel zippy rumble jet nitro vibe groove funk boom dash zoom
atlas titan thor juno echo iris nyx zeus odin hera luna ares
freya loki isis rhea vega aardvark ant ape aphid asp baboon badger
bass bat bear beaver bee beetle bird blackbird boa boar bobcat bug
buzzard camel carp cat catfish cattle cheetah chicken chipmunk clam cobra cod
condor cougar cow coyote crab crayfish cricket crow cuckoo deer dingo dog
dolphin donkey dormouse dove dragon duck eagle earthworm eel egret elk emu
ermine fish flea fly fowl fox frog gazelle gerbil gibbon giraffe goat
goldfish goose gopher grouse gull guppy haddock hamster hare hedgehog herring hornet
horse jackal jaguar jay kite krill lamprey lark leech lemming lemur leopard
lion lizard llama lobster locust loon lungfish macaw magpie mammal mandrill marlin
marten mink minnow mite mole mollusk mongoose monkey moth mouse mule orca
ostrich owl ox panther parrot partridge peacock peafowl penguin perch pheasant pig
pigeon pike pony porpoise possum prawn primate puffin python quail rabbit raccoon
rat reindeer reptile rodent rook rooster sailfish salmon scallop shark sheep shrimp
silkworm skunk sloth slug smelt snail snake snipe sole sparrow spider squid
squirrel starfish stork sturgeon swallow swift swordfish termite tern thrush tick toad
tortoise trout tuna turkey turtle viper vulture walrus warbler wasp weasel whale
whitefish wildcat wombat worm wren yak zebra aqua beige black blue blush
bronze brown chocolate coffee copper cyan emerald gold gray green lime maroon
orange pink purple red rose scarlet silver tan turquoise violet white yellow
able absent abstract active actual acute added advanced agreed alert alive allied
alone alright amused ancient asleep average awake aware awful back balanced bare
basic better big bizarre blank blonde blushing boiling bold bottom brainy brave
breezy brief bright brilliant broad bumpy burning busy calm careful casual central
certain changing charming cheerful chief chilly chosen chubby civic civil classic clean
clear clever close closed cloudy coastal cold coloured combined common compact complete
complex concrete conscious constant content cooing cool corporate correct crucial cuddly curly
current curved cute daily damp dark dear decent deep detailed different direct
dirty distant distinct diverse divine dizzy double driving dry dual due dusty
eager early eastern easy eerie eldest empty endless equal exact extra extreme
faint fair faithful famous fancy far fast federal fellow fierce final fine
firm fiscal fit fixed flaky flat fluffy flying fond formal forward free
frequent fresh friendly front frozen full fun funny future fuzzy general gentle
giant glad gleaming global golden good gorgeous gothic graceful grand grateful greasy
great growing handsome happy hard head healthy heavy helpful hidden high hissing
hollow homely hon honest hot huge human hushed husky icy ideal immense
impressed improved inclined increased inland inner instant intact intense interim involved itchy
joint jolly joyous juicy junior keen key kind large late latin leading
left legal lengthy lesser level light like likely liquid little live lively
living local long loose loud lovely low loyal lucky mad magic main
major mammoth marine marked married mass massive mature mean melted mere mid
middle mighty mild minor misty mixed mobile modern modest monthly moral muddy
mushy narrow national native natural naval near nearby neat net neutral new
nice noble noisy normal northern nosy novel nutty odd old open opposite
oral outdoor outer outside pale partial passing past patient peaceful perfect petite
plain planned plastic pleasant pleased poised polite poor precious precise preferred premier
prepared present pretty prime printed prior private profound proper proposed proud public
puny pure purring puzzled quaint quick quickest quiet rainy random rapid rare
raspy rational raw ready real rear recent reduced relaxed relieved remote renewed
required retail rich right rigid ripe rising rival roasted robust rolling rough
round royal rubber ruling running rural sad safe salty secret secure select
senior separate shallow shared sharp sheer shiny short shy silent silky silly
simple single skilled sleepy slight slim slow small smart smiling smooth social
soft solar solid sound southern spare sparkling spatial special spicy splendid sporting
spotless spotty square stable standard static steady steep sticky stiff stormy straight
strange strict striking striped strong subtle sudden sunny super superb supreme sure
sweet tall tame tart tasty teenage tender tense thick thin thorough thoughtful
tight tiny tired top total tough tricky unique upper urban useful valid
varied vast verbal vital vivid vocal warm wealthy wee weekly weird welcome
western wet whole wide widespread wild willing wily wise wispy witty wooden
working worldwide worthwhile worthy written yearling yearning yielding young youngest youthful yummy
zany zestful account action ad address air airline airplane airport alarm angle
answer apple arm art autumn balloon beach beard bed bit book boots
branch breakfast byte camera candle car carpet cartoon city coat crayon dawn
daybreak diamond dinner dream dress egg eggplant engine eve evening eye fall
flag flower football forest fountain france garage garden gas ghost glass grass
guitar hair helmet house ice insect iron island jelly joystick juice keyboard
kitchen knife lamp laptop leather lighter lock lunch machine market match midnight
morn morning nail napkin needle nest night nightfall noon notebook ocean oil
oyster pager painting park pencil pillow pizza planet printer quill rainbow raincoat
ram river room sandwich scooter shampoo shoe smartphone soccer solstice spoon spring
state stone sugar summer sundown sunset table tent toothbrush traffic train truck
twilight van vase wall window winter wire yacht zoo bashful beefy bent
best billions bland boundless brash bulky burly cagey callous creamy dazzling gifted
hallowed howling hundreds millions plump rapping refined rhythmic scarce scruffy shapely sparse
stocky teeny thankful thousands tinkling work life world down home part game
thing end keep number lot set group change point support power stop
water side line run service face story course means post court hand
body control food hit watch stay deal turn check form heart fire
phone building plan works street type chance study board cut field moment
road force issue rest space term date land shot record club film
lead share center couple hold return star view break event design king
bank press bill ground source stand stuff drive felt model picture size
step range trade cup led lower style stage release cover door pick
sign staff union walk figure paper earth goal sea ways access base
pass ball box card mine piece growth response rock album charge effect
network store track weight beat pressure station cross focus join section speed
contact drop link nature movement photo safety scene sun coach subject centre
hotel leader product unit bar brain floor image rule approach defense master
ship stock band fan impact wear color luck skin drink trip plant
spot block shop catch cell coast foot hall pop weather flight heat
queen channel exchange fell finding ride screen tree structure wind brand bus
lake mouth scale score surface throw arms click fashion feature hill metal
pull push seat target agent draw ring rise spread waste grade remains
bag camp cast handle till helping produce wood background bridge copy host
housing journal length setting balance boss map stick volume wake corner driver
farm guide raise roll treat edge web bay core guard mountain port
shoot steps stress taste tea clothes fuel links mail plane quarter sky
valley boat mix path purchase steel turning border moon proof suit chair
launch ray express hero shopping transport device entry feed platform pool route
smoke hole leg max milk pack sector chain fake measure split aircraft
escape fault fill bowl display falls meat neck shirt zero cream serving
signal stream wave cutting draft humans spoke wing cycle row salt switch
bell blow bond motion prize drawing favor frame guest kiss load rent
bottle chat cheese diet fruit item lane mess shift storage tank yard
button counter crown pattern rooms tool carbon circle mate panel plate relief
rice roof tip baseball bathroom cable hide irish print bike cake hat
motor peak portion protein sample seats breath chest grab paint pilot shipping
steam cap defence nose semi tie bread eggs facing gang hanging lift
shoulder shower tower wheel bush cabinet coal colour highway monster speaker auto
finger grey heading meal pants pocket rush bone chamber chart circuit clothing
gap gate mirror mount bedroom bound cloud colors gear hip package railway
shock soldier wash acid angel bars castle covering flash fort mac palace
pet temple trail assault bath chase jimmy mini sand tag tape thread
clock desk ear grounds gym horror label output pitch worker android belt
kit lab morgan na soil trash virus walker bureau comfort crack deck
dust mum rail root butter crystal decline forth hop landing layer pot
"""
WORDLIST = _WORD_TEXT.split()
del _WORD_TEXT

_CODENAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,38}$")

def is_valid_codename(s: str) -> bool:
    return bool(_CODENAME_RE.match(s))

def suggest_unused(existing: set[str]) -> str:
    pool = [word for word in WORDLIST if word not in existing]
    if pool:
        return random.choice(pool)
    base = random.choice(WORDLIST)
    suffix = 2
    while f"{base}-{suffix}" in existing:
        suffix += 1
    return f"{base}-{suffix}"
